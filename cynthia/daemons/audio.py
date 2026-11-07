"""Capture game audio from the capture card into the shared audio ring."""

import logging
import os
import select
import subprocess
import threading
import time
from pathlib import Path

import numpy

from cynthia.utils.log import get_logger

from .daemon import Daemon
from .frames import AUDIO_BYTES_PER_SEC, AUDIO_FRAME_BYTES

logger = get_logger(__name__, logging.INFO)

ASOUND_CARDS = Path("/proc/asound/cards")
# About 10 ms of audio per read keeps the capture timestamps tight
READ_BYTES = AUDIO_BYTES_PER_SEC // 100 // AUDIO_FRAME_BYTES * AUDIO_FRAME_BYTES
STALL_SECONDS = 3
RETRY_SECONDS = 2
# The card often isn't ready the first time after boot or a mode switch;
# only warn once capture has failed this many times in a row
WARN_AFTER_FAILURES = 3


class DropoutRepair:
    """Smooth over the dropouts the Elgato 4K X puts in its audio.

    Captured faults have a discontinuity about a millisecond (one USB packet)
    before one garbage frame and three all-zero frames; both are heard as pops.
    Quiet quantized audio can also have three-zero runs, so require an abrupt
    preceding frame or packet discontinuity. Reconstruct the whole damaged
    packet, not just its edges, from forward and backward predictions of the
    good neighbouring audio.
    Hold enough audio for both prediction windows so repair does not depend on
    where a pipe read ends.
    """

    ZEROS = 3
    PACKET = 208 // AUDIO_FRAME_BYTES  # maximum Elgato USB audio packet
    ORDER = 16
    CONTEXT = 128
    HOLD = PACKET + CONTEXT + ZEROS + 2

    def __init__(self):
        """Start with no held-back audio."""
        self._held = numpy.zeros((0, 2), numpy.int16)
        self._context = numpy.zeros((0, 2), numpy.int16)
        self._emitted = 0
        self._repaired_until = -1
        self.repaired = 0

    @classmethod
    def _predict(cls, context, count):
        """Extrapolate a short gap, bounding ill-conditioned audio predictions."""
        mean = context.mean()
        signal = context - mean
        order = min(cls.ORDER, len(signal) // 4)
        if not order or numpy.mean(signal**2) < 1:
            return numpy.full(count, context[-1])
        windows = numpy.lib.stride_tricks.sliding_window_view(signal, order + 1)
        design = windows[:, :order][:, ::-1]
        gram = design.T @ design
        regularization = max(1, numpy.trace(gram) / order * 1e-5)
        try:
            coefficients = numpy.linalg.solve(
                gram + numpy.eye(order) * regularization,
                design.T @ windows[:, order],
            )
        except numpy.linalg.LinAlgError:
            return numpy.full(count, context[-1])
        history = list(signal[-order:])
        predicted = []
        limit = max(1, 2 * numpy.abs(context).max())
        for _ in range(count):
            sample = float(numpy.dot(coefficients, history[-order:][::-1]))
            if not numpy.isfinite(sample) or abs(sample + mean) > limit:
                return numpy.full(count, context[-1])
            history.append(sample)
            predicted.append(sample + mean)
        return numpy.asarray(predicted)

    def _repair(self, frames, garbage, after):
        """Reconstruct the corrupt USB packet without introducing short ramps."""
        splice = max(1, garbage - self.PACKET)
        count = after - splice
        blend = (0.5 - 0.5 * numpy.cos(numpy.linspace(0, numpy.pi, count)))[:, None]
        before = frames[max(0, splice - self.CONTEXT) : splice]
        following = frames[after : after + self.CONTEXT]
        forward = numpy.column_stack(
            [self._predict(before[:, channel], count) for channel in range(2)]
        )
        backward = numpy.column_stack(
            [
                self._predict(following[::-1, channel], count)[::-1]
                for channel in range(2)
            ]
        )
        frames[splice:after] = forward * (1 - blend) + backward * blend

    def process(self, data):
        """Return repaired whole frames from `data`, keeping a short tail back."""
        new = numpy.frombuffer(data, numpy.int16).reshape(-1, 2)
        context = len(self._context)
        frames = numpy.concatenate([self._context, self._held, new])
        zero = ~frames.any(axis=1)
        edges = numpy.diff(numpy.concatenate([[0], zero.view(numpy.int8), [0]]))
        starts = numpy.flatnonzero(edges == 1)
        ends = numpy.flatnonzero(edges == -1)
        work = None
        for start, end in zip(starts, ends):
            absolute_end = self._emitted - context + end
            # Needs a good frame on each side of the garbage frame and zeros
            if (
                end - start != self.ZEROS
                or start < 2
                or end + self.CONTEXT > len(frames)
                or absolute_end <= self._repaired_until
            ):
                continue
            if not ((frames[start - 1] > 16) | (frames[start - 1] < -16)).any():
                packet = frames[
                    max(0, start - self.PACKET - 12) : max(0, start - 32)
                ].astype(float)
                if (
                    len(packet) < 3
                    or numpy.abs(numpy.diff(packet, 2, axis=0)).max() <= 64
                ):
                    continue
            if work is None:
                work = frames.astype(float)
            self._repair(work, start - 1, end)
            self._repaired_until = absolute_end
            self.repaired += 1
        if work is not None:
            frames = numpy.clip(numpy.round(work), -32768, 32767).astype(numpy.int16)
        cut = max(context, len(frames) - self.HOLD)
        out, self._held = frames[context:cut], frames[cut:]
        self._context = frames[:cut][-self.CONTEXT :]
        self._emitted += len(out)
        return out.tobytes()


def find_audio_device(env=None):
    """Return the ALSA capture device: `AUDIO_DEVICE`, else the Elgato card."""
    configured = env.get("AUDIO_DEVICE", None) if env is not None else None
    if configured:
        return configured
    try:
        for line in ASOUND_CARDS.read_text().splitlines():
            if "elgato" in line.lower() and "[" in line:
                card_id = line.split("[", 1)[1].split("]", 1)[0].strip()
                return f"plughw:CARD={card_id}"
    except OSError:
        pass
    return None


def capture_command(device):
    """Build the ffmpeg command that writes raw 48 kHz stereo PCM to stdout."""
    return [
        "ffmpeg",
        "-nostdin",
        "-loglevel",
        "error",
        "-fflags",
        "nobuffer",
        "-flags",
        "low_delay",
        "-probesize",
        "32",
        "-analyzeduration",
        "0",
        "-f",
        "alsa",
        "-i",
        device,
        "-f",
        "s16le",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-flush_packets",
        "1",
        "-",
    ]


def _stop(proc):
    """Terminate a capture process and wait briefly for it."""
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def audio_wanted(uns):
    """Whether anything consumes audio: a web listener, WebRTC or the OBS feed."""
    return bool(
        getattr(uns, "audio_listeners", 0)
        or getattr(uns, "obs_feeding", False)
        or getattr(uns, "webrtc_feeding", False)
    )


def drain_stderr(proc, errors):
    """Collect capture errors; an unread pipe would block ffmpeg."""
    for line in iter(proc.stderr.readline, b""):
        text = line.decode(errors="replace").strip()
        if text:
            errors.append(text)
            del errors[:-20]
            logger.debug("Audio capture: %s", text)


class AudioDaemon(Daemon):
    """Read PCM from the capture card and publish it with capture timestamps."""

    def __init__(self, dman):
        """Resolve the capture device and start the capture process."""

        def loop(ns, uns, audio_ring, device, env):
            """Keep a capture running, restarting it if it fails or stalls."""
            if not device:
                logger.warning("No audio capture device found; will keep looking.")
            failures = 0
            while ns.run:
                if not device:
                    # The card may enumerate after startup or be plugged in later
                    time.sleep(RETRY_SECONDS)
                    device = find_audio_device(env)
                    continue
                if not audio_wanted(uns):
                    # Nobody is listening, so leave the capture device alone
                    time.sleep(0.25)
                    continue
                proc = subprocess.Popen(
                    capture_command(device),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                )
                (logger.debug if failures else logger.info)(
                    "Capturing audio from `%s`", device
                )
                errors = []
                threading.Thread(
                    target=drain_stderr, args=(proc, errors), daemon=True
                ).start()
                fd = proc.stdout.fileno()
                last_data = time.monotonic()
                carry = b""
                repair = DropoutRepair()
                partial_reads = 0
                got_data = False
                try:
                    while ns.run and audio_wanted(uns):
                        # The timeout lets us notice shutdown and a silent device
                        if not select.select([fd], [], [], 0.5)[0]:
                            if time.monotonic() - last_data > STALL_SECONDS:
                                break
                            continue
                        data = os.read(fd, READ_BYTES)
                        if not data:
                            break
                        last_data = time.monotonic()
                        if not got_data:
                            got_data = True
                            if failures >= WARN_AFTER_FAILURES:
                                logger.info("Audio capture recovered.")
                            failures = 0
                        # A pipe read can end mid-frame; the ring only takes whole
                        # frames, so keep the tail or later audio shifts by a
                        # sample and swaps channels, which sounds like a click.
                        data = carry + data
                        cut = len(data) - len(data) % AUDIO_FRAME_BYTES
                        carry = data[cut:]
                        if carry:
                            partial_reads += 1
                            if partial_reads in (1, 100, 10_000):
                                logger.info(
                                    "Audio capture: %s reads ended mid-frame",
                                    partial_reads,
                                )
                        repaired = repair.repaired
                        audio_ring.write(repair.process(data[:cut]), time.time_ns())
                        if not repaired and repair.repaired:
                            logger.info(
                                "Audio capture has card dropouts; smoothing them over."
                            )
                finally:
                    _stop(proc)
                if not ns.run:
                    break
                if not audio_wanted(uns):
                    logger.info("No audio consumers; capture stopped.")
                    continue
                reason = "; ".join(errors[-3:]) or "no data"
                if got_data:
                    # A running capture dropped out: always worth a warning
                    logger.warning("Audio capture stopped; restarting: %s", reason)
                    time.sleep(RETRY_SECONDS)
                    continue
                failures += 1
                if failures == WARN_AFTER_FAILURES:
                    logger.warning(
                        "Audio capture keeps failing; still retrying: %s", reason
                    )
                elif failures < WARN_AFTER_FAILURES:
                    logger.debug("Audio capture stopped; restarting: %s", reason)
                time.sleep(RETRY_SECONDS)

        super().__init__(
            dman,
            find_audio_device(dman.context.env),
            dman.context.env,
            audio_ring=True,
        )
        self.loop = loop
        self.start()
