"""Text to speech with Piper voices, run on the CPU so the GPU stays free.

Voices are named like `en_US-amy-medium` (see `/llm voices`) and are
downloaded on first use. Change voices with `tts_voice`; multi-speaker voices
also take `tts_speaker`.
"""

import asyncio
import json
import logging
import re
import tempfile
import threading
import time
import wave
from pathlib import Path
from urllib.request import urlopen

import numpy

from .client import setting

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "en_US-amy-medium"
VOICES_JSON = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/voices.json?download=true"
)
CATALOG_SECONDS = 24 * 3600
URL = re.compile(r"https?://\S+", re.I)
EMOTE = re.compile(r"(?<!\w)[:;]-?[()DPp3]|<3|\b[A-Z][a-z]+[A-Z][A-Za-z0-9]*\b")


# Speech level on stream, as the average power (dBFS) of its voiced parts,
# matching OBS's meter. -20 sits about 9 dB over the game feed (~-29 dBFS), so
# the voice is clear without drowning out the game
DEFAULT_LOUDNESS = -20.0
# Peak ceiling after normalizing, in dBFS
PEAK_CEILING = -1.0
# Parts quieter than this (dBFS, 20 ms windows) are pauses, not speech
SILENCE = -45.0


def normalize(samples, rate, target=DEFAULT_LOUDNESS, ceiling=PEAK_CEILING):
    """Scale int16 `samples` so speech averages `target` dBFS, peaks soft-limited.

    Every Piper voice comes out at a different level; this keeps them all at
    the same place in the stream mix.
    """
    audio = samples.astype(numpy.float64) / 32768
    window = max(int(rate * 0.02), 1)
    frames = audio[: len(audio) // window * window].reshape(-1, window)
    if not len(frames):
        return samples
    power = numpy.mean(frames**2, axis=1)
    voiced = power[power > 10 ** (SILENCE / 10)]
    if not len(voiced):
        return samples
    level = 10 * numpy.log10(numpy.mean(voiced))
    audio = audio * 10 ** ((target - level) / 20)
    # Soft knee from 6 dB under the ceiling, so loud syllables round off
    # instead of clipping
    limit = 10 ** (ceiling / 20)
    knee = limit / 2
    loud = numpy.abs(audio) > knee
    audio[loud] = numpy.sign(audio[loud]) * (
        knee
        + (limit - knee) * numpy.tanh((numpy.abs(audio[loud]) - knee) / (limit - knee))
    )
    return numpy.round(audio * 32767).astype(numpy.int16)


def normalize_file(path, target=DEFAULT_LOUDNESS):
    """Normalize a mono or stereo 16-bit WAV file in place."""
    with wave.open(str(path), "rb") as wav:
        params = wav.getparams()
        samples = numpy.frombuffer(wav.readframes(params.nframes), dtype=numpy.int16)
    if params.sampwidth != 2:
        return
    samples = normalize(samples, params.framerate * params.nchannels, target)
    with wave.open(str(path), "wb") as wav:
        wav.setparams(params)
        wav.writeframes(samples.tobytes())


class VoiceError(Exception):
    """Raised when a voice can't be loaded or used."""


def speakable(text):
    """Text as it should be read aloud: no links, emotes, or @ signs."""
    text = URL.sub("", text)
    text = EMOTE.sub("", text)
    text = re.sub(r"@(\w+)", lambda m: m.group(1).replace("_", " "), text)
    return " ".join(text.split())


class Voice:
    """Synthesize speech to WAV files with the configured Piper voice."""

    def __init__(self, config):
        """Use `config` for the voice name, folder and speaking style."""
        self.config = config
        self.lock = threading.Lock()
        self.loaded = (None, None)
        self.catalog_cache = (0.0, None)

    @property
    def name(self):
        """Configured Piper voice name."""
        return str(setting(self.config, "tts_voice", DEFAULT_VOICE)).strip()

    @property
    def folder(self):
        """Folder holding downloaded voices and generated speech."""
        default = Path.home() / ".local" / "share" / "cynthia" / "voices"
        path = Path(str(setting(self.config, "tts_voice_dir", default))).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def model(self):
        """Load the configured voice, downloading it first if needed."""
        from piper import PiperVoice
        from piper.download_voices import download_voice

        name = self.name
        if self.loaded[0] == name:
            return self.loaded[1]
        path = self.folder / f"{name}.onnx"
        if not path.exists() or not path.with_suffix(".onnx.json").exists():
            logger.info("Downloading Piper voice %s.", name)
            try:
                download_voice(name, self.folder)
            except Exception as e:
                for partial in (path, path.with_suffix(".onnx.json")):
                    partial.unlink(missing_ok=True)
                raise VoiceError(f"Couldn't download voice `{name}`: {e}") from e
        voice = PiperVoice.load(str(path))
        self.loaded = (name, voice)
        return voice

    def synthesize(self, text, path):
        """Speak `text` into the WAV file `path`; returns its length in seconds."""
        from piper import SynthesisConfig

        text = speakable(text)
        if not text:
            raise VoiceError("Nothing to say.")
        speaker = setting(self.config, "tts_speaker", None)
        options = SynthesisConfig(
            speaker_id=None if speaker is None else int(speaker),
            length_scale=1 / float(setting(self.config, "tts_speed", 1.0)),
        )
        with self.lock:
            voice = self.model()
            with wave.open(str(path), "wb") as wav:
                voice.synthesize_wav(text, wav, syn_config=options)
        target = float(setting(self.config, "tts_loudness", DEFAULT_LOUDNESS))
        normalize_file(path, target)
        with wave.open(str(path), "rb") as wav:
            return wav.getnframes() / wav.getframerate()

    async def speak_to_file(self, text, name="speech.wav"):
        """Synthesize `text` off the event loop; returns `(path, seconds)`."""
        path = self.folder / name
        seconds = await asyncio.to_thread(self.synthesize, text, path)
        return path, seconds

    def catalog(self):
        """All downloadable Piper voices, keyed by name (cached for a day)."""
        at, voices = self.catalog_cache
        if voices is None or time.time() - at > CATALOG_SECONDS:
            with urlopen(VOICES_JSON, timeout=20) as response:
                voices = json.load(response)
            self.catalog_cache = (time.time(), voices)
        return voices

    def installed(self):
        """Names of voices already downloaded."""
        return sorted(p.name[: -len(".onnx")] for p in self.folder.glob("*.onnx"))


class Speaker:
    """Play synthesized speech into the stream one line at a time."""

    def __init__(self, voice, obs):
        """Speak with `voice` through the `obs` controller."""
        self.voice = voice
        self.obs = obs
        self.lock = asyncio.Lock()
        self.turn = 0
        self.playback = tempfile.TemporaryDirectory(prefix="cynthia-voice-")
        Path(self.playback.name).chmod(0o755)

    async def say(self, text):
        """Speak `text` on stream and wait until it finishes; returns seconds."""
        async with self.lock:
            # Alternate files so a new line never overwrites one OBS is reading
            self.turn ^= 1
            path, seconds = await self.voice.speak_to_file(
                text, str(Path(self.playback.name) / f"stream-{self.turn}.wav")
            )
            path.chmod(0o644)
            volume = float(setting(self.voice.config, "tts_stream_volume", 1.0))
            if not await asyncio.to_thread(self.obs.play_audio, str(path), volume):
                logger.warning("OBS didn't start playing %s.", path.name)
                return 0.0
            await asyncio.sleep(seconds + 0.3)
            return seconds
