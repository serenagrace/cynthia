"""Send captured frames to OBS through a hardware-encoded local video feed."""

import logging
import os
import socket
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

import numpy

from cynthia.utils.log import get_logger
from cynthia.utils.streamcfg import setting, size_for

from .daemon import Daemon
from .dman import FB0
from .frames import AUDIO_BYTES_PER_SEC, AUDIO_FRAME_BYTES

logger = get_logger(__name__, logging.INFO)

OBS_POLL_SECONDS = 2
DATAGRAM_BYTES = 1316  # seven MPEG-TS packets
# ffmpeg holds video back until audio catches up with it. Audio that falls this
# far behind the wall clock (a stalled pump, or ring data skipped to stay live)
# never recovers by itself and drags the video down to a few frames a second.
AUDIO_LAG_LIMIT = 0.15
AUDIO_LAG_KEEP = 0.03
# Smaller lags are absorbed by stretching the audio a little, which keeps video
# from being throttled and is too slight to hear
AUDIO_STRETCH_DEADBAND = 0.01
AUDIO_STRETCH_MAX = 0.02
OBS_PROCESS_NAMES = ("obs", "obs-studio")
# Ignore startup, then require two slow windows before recycling an encoder.
FEED_WATCH_SECONDS = 15
FEED_SLOW_WINDOWS = 2
FEED_MIN_RATIO = 0.5


def obs_running(proc=Path("/proc")):
    """Whether an OBS Studio process is running."""
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if (entry / "comm").read_text().strip() in OBS_PROCESS_NAMES:
                return True
        except OSError:
            continue
    return False


def vbv_args(bitrate, seconds):
    """Cap the rate buffer so keyframes are spread out instead of sent in a burst.

    Lost packets corrupt the picture of a WebRTC viewer until the next keyframe,
    and a large keyframe sent at once overflows socket buffers.
    """
    if not seconds:
        return []
    units = {"k": 1_000, "m": 1_000_000}
    text = str(bitrate).strip().lower()
    scale = units.get(text[-1], 1)
    bits = int(float(text.rstrip("km")) * scale)
    return ["-maxrate", str(bits), "-bufsize", str(int(bits * seconds))]


def ffmpeg_command(
    port,
    fps,
    bitrate,
    audio_fd=None,
    relay=False,
    height=FB0.HEIGHT,
    audio_codec="aac",
    gop_seconds=2,
    vbv_seconds=None,
    native=False,
):
    """Build the ffmpeg command that turns raw frames into an NVENC stream.

    `native` frames are the card's NV12, which NVENC takes as they are; the
    default is BGR, which ffmpeg must convert on the CPU first.

    H.264 is used because Twitch requires it and YouTube accepts it, so OBS can
    pass the feed on without re-encoding choices changing later. The stream is
    MPEG-TS, which carries the AAC audio track alongside the video. Both inputs
    arrive live; only the video input is stamped with the wall clock, since
    wall-clock stamps on the audio pipe starve the muxer of audio packets.
    """
    audio_input = []
    audio_output = []
    if audio_fd is not None:
        audio_input = [
            "-f",
            "s16le",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-i",
            f"pipe:{audio_fd}",
            "-map",
            "0:v",
            "-map",
            "1:a",
        ]
        audio_output = [
            "-af",
            "aresample=async=1000",
            "-c:a",
            "libopus" if audio_codec == "opus" else "aac",
            "-b:a",
            "128k" if audio_codec == "opus" else "192k",
            "-ar",
            "48000",
        ]
    if relay:
        # A delayed feed leaves ffmpeg through a pipe and is sent by `Feed`
        output = ["-flush_packets", "1", "pipe:1"]
    else:
        output = [f"udp://127.0.0.1:{port}?pkt_size={DATAGRAM_BYTES}"]
    return [
        "ffmpeg",
        "-nostdin",
        "-loglevel",
        "error",
        "-use_wallclock_as_timestamps",
        "1",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "nv12" if native else "bgr24",
        "-video_size",
        f"{FB0.WIDTH}x{FB0.HEIGHT}",
        *(["-color_range", "tv", "-colorspace", "bt709"] if native else []),
        "-i",
        "-",
        *audio_input,
        "-vf",
        video_filter(height, native),
        "-fps_mode",
        "cfr",
        "-r",
        str(fps),
        "-c:v",
        "h264_nvenc",
        "-preset",
        "p4",
        "-tune",
        "ll",
        "-rc",
        "cbr",
        "-b:v",
        bitrate,
        *vbv_args(bitrate, vbv_seconds),
        "-bf",
        "0",
        "-g",
        str(fps * gop_seconds),
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-colorspace",
        "bt709",
        "-color_range",
        "tv",
        *audio_output,
        # One PES packet per frame and no mux delay: the default packs about
        # 180 ms of audio into each packet, which arrives in bursts
        "-pes_payload_size",
        "0",
        "-muxdelay",
        "0",
        "-muxpreload",
        "0",
        "-f",
        "mpegts",
        *output,
    ]


def video_filter(height, native):
    """The filter that brings captured frames to the output size, as NV12."""
    width, height = size_for(height)
    if native:
        # The card's NV12 is already limited-range BT.709, so only resize
        if (width, height) == (FB0.WIDTH, FB0.HEIGHT):
            return "null"
        return f"scale={width}:{height}:flags=bicubic,format=nv12"
    return f"scale={width}:{height}:out_color_matrix=bt709:out_range=tv,format=nv12"


def audio_shortfall(elapsed, delivered):
    """Bytes of silence that bring delivered audio back to the wall clock.

    Returns 0 until audio is more than `AUDIO_LAG_LIMIT` seconds behind, so
    small timing jitter never inserts silence.
    """
    behind = elapsed * AUDIO_BYTES_PER_SEC - delivered
    if behind <= AUDIO_LAG_LIMIT * AUDIO_BYTES_PER_SEC:
        return 0
    behind -= AUDIO_LAG_KEEP * AUDIO_BYTES_PER_SEC
    return int(behind) - int(behind) % AUDIO_FRAME_BYTES


def audio_stretch(chunk, elapsed, delivered):
    """Return `chunk` stretched to pull delivered audio level with real time.

    Audio from the capture card runs a fraction of a percent slow, and ffmpeg
    throttles the video to match once that lag builds up. Each chunk is
    resampled slightly longer, by at most `AUDIO_STRETCH_MAX`, until the lag is
    inside `AUDIO_STRETCH_DEADBAND`.
    """
    frames = len(chunk) // AUDIO_FRAME_BYTES
    behind = elapsed * AUDIO_BYTES_PER_SEC - delivered
    if frames < 2 or behind <= AUDIO_STRETCH_DEADBAND * AUDIO_BYTES_PER_SEC:
        return chunk
    extra = min(int(behind / AUDIO_FRAME_BYTES / 10), int(frames * AUDIO_STRETCH_MAX))
    if extra < 1:
        return chunk
    samples = numpy.frombuffer(chunk, numpy.int16, frames * 2).reshape(frames, 2)
    source = numpy.arange(frames)
    target = numpy.linspace(0, frames - 1, frames + extra)
    stretched = numpy.empty((frames + extra, 2), numpy.int16)
    for channel in range(2):
        stretched[:, channel] = numpy.interp(target, source, samples[:, channel])
    return stretched.tobytes()


class Feed:
    """One ffmpeg encoder plus the thread that pumps audio into it."""

    SILENCE = bytes(AUDIO_BYTES_PER_SEC // 10)

    def __init__(
        self,
        port,
        fps,
        bitrate,
        audio_ring,
        delay_ms=0,
        height=FB0.HEIGHT,
        audio_codec="aac",
        gop_seconds=2,
        vbv_seconds=None,
        native=False,
        source_ring=None,
    ):
        """Start ffmpeg reading video from stdin and PCM audio from a pipe.

        With `delay_ms` above zero the encoded stream is held back that long
        before it is sent, which smooths the feed without buffering raw frames.
        """
        self.audio_ring = audio_ring
        self.frames_written = 0
        self.delay = delay_ms / 1000
        self._held = deque()
        self._ready = threading.Condition()
        read_fd, self._audio_fd = os.pipe()
        try:
            self.proc = subprocess.Popen(
                ffmpeg_command(
                    port,
                    fps,
                    bitrate,
                    read_fd,
                    relay=self.delay > 0,
                    height=height,
                    audio_codec=audio_codec,
                    gop_seconds=gop_seconds,
                    vbv_seconds=vbv_seconds,
                    native=native,
                ),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE if self.delay > 0 else None,
                stderr=subprocess.PIPE,
                pass_fds=(read_fd,),
            )
        finally:
            os.close(read_fd)
        self._stopped = threading.Event()
        self._pump = threading.Thread(
            target=self._pump_audio, name="obs-audio", daemon=True
        )
        self._pump.start()
        self._relay = []
        if self.delay > 0:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._target = ("127.0.0.1", port)
            for target in (self._hold_output, self._send_held):
                thread = threading.Thread(target=target, name="obs-delay", daemon=True)
                thread.start()
                self._relay.append(thread)
        self._watchdog = None
        if source_ring is not None:
            self._watchdog = threading.Thread(
                target=self._watch_video,
                args=(source_ring, fps),
                name="feed-watchdog",
                daemon=True,
            )
            self._watchdog.start()

    def _watch_video(self, source_ring, fps):
        """Recycle an encoder that consumes too few fresh frames despite live capture.

        Compare sequence numbers, not image hashes: a static game screen is still
        healthy video. Cap the expectation at the output rate, so a 60 fps OBS
        feed consuming a 30 fps capture is not mistaken for a stalled encoder.
        """
        if self._stopped.wait(FEED_WATCH_SECONDS):
            return
        last_seq = source_ring.seq
        last_written = self.frames_written
        last_time = time.monotonic()
        slow_windows = 0
        while not self._stopped.wait(FEED_WATCH_SECONDS):
            if self.proc.poll() is not None:
                return
            now = time.monotonic()
            seq, written = source_ring.seq, self.frames_written
            elapsed = max(now - last_time, 0.001)
            available_fps = (seq - last_seq) / elapsed
            actual_fps = (written - last_written) / elapsed
            expected_fps = min(fps, available_fps)
            # Missing capture is the capture supervisor's responsibility, not FFmpeg's.
            slow = expected_fps >= 5 and actual_fps < expected_fps * FEED_MIN_RATIO
            slow_windows = slow_windows + 1 if slow else 0
            if slow_windows >= FEED_SLOW_WINDOWS:
                logger.warning(
                    "Feed encoder consuming %.1f/%.1f fresh fps for %s seconds; "
                    "recycling FFmpeg (pid %s).",
                    actual_fps,
                    expected_fps,
                    FEED_WATCH_SECONDS * FEED_SLOW_WINDOWS,
                    self.proc.pid,
                )
                # Kill only this encoder: its daemon handles the existing retry/backoff.
                # This also releases a writer blocked inside a raw-frame pipe write.
                self.proc.kill()
                return
            last_seq, last_written, last_time = seq, written, now

    def _hold_output(self):
        """Read the encoded stream and queue whole datagrams with arrival times."""
        fd = self.proc.stdout.fileno()
        pending = b""
        while not self._stopped.is_set():
            try:
                data = os.read(fd, 65536)
            except OSError:
                break
            if not data:
                break
            pending += data
            now = time.monotonic()
            with self._ready:
                while len(pending) >= DATAGRAM_BYTES:
                    self._held.append((now, pending[:DATAGRAM_BYTES]))
                    pending = pending[DATAGRAM_BYTES:]
                self._ready.notify()

    def _send_held(self):
        """Send each queued datagram once it has been held for the delay."""
        while not self._stopped.is_set():
            with self._ready:
                if not self._held:
                    self._ready.wait(0.2)
                    continue
                due = self._held[0][0] + self.delay
            wait = due - time.monotonic()
            if wait > 0:
                time.sleep(min(wait, 0.05))
                continue
            with self._ready:
                _, datagram = self._held.popleft()
            try:
                self._socket.sendto(datagram, self._target)
            except OSError:
                pass

    def _pump_audio(self):
        """Copy ring audio to ffmpeg, keeping its timeline level with real time.

        Silence fills gaps so muxing never stalls, small lags are stretched
        away, and a large shortfall is padded; see `audio_stretch` and
        `AUDIO_LAG_LIMIT`.
        """
        pos = self.audio_ring.live_position(60)
        started = time.monotonic()
        delivered = 0
        gaps = skips = pads = 0
        report_at = started + 30
        while not self._stopped.is_set():
            data, pos, _, skipped = self.audio_ring.read(pos, 0.1, max_lag_ms=500)
            gaps += not data
            skips += bool(skipped)
            chunk = audio_stretch(
                data or self.SILENCE, time.monotonic() - started, delivered
            )
            try:
                os.write(self._audio_fd, chunk)
                delivered += len(chunk)
                pad = audio_shortfall(time.monotonic() - started, delivered)
                if pad:
                    os.write(self._audio_fd, bytes(pad))
                    delivered += pad
                    pads += 1
            except OSError:
                return
            if time.monotonic() >= report_at:
                if gaps or skips or pads:
                    logger.warning(
                        "Audio feed in 30 s: %s silent gaps, %s jumps ahead, "
                        "%s catch-up pads",
                        gaps,
                        skips,
                        pads,
                    )
                gaps = skips = pads = 0
                report_at = time.monotonic() + 30

    def write_claim(self, claim):
        """Copy a claimed ring frame, release it, then send the copy to ffmpeg.

        A pipe write of a raw frame can take tens of milliseconds, so the ring
        slot is freed first; holding it would starve the capture writer.
        """
        if getattr(self, "_copy", None) is None:
            self._copy = claim.frame.copy()
        else:
            self._copy[:] = claim.frame
        claim.release()
        return self.write_frame(self._copy)

    def write_frame(self, frame):
        """Send one raw video frame; returns False once ffmpeg has gone away."""
        try:
            self.proc.stdin.write(frame.data)
            self.frames_written += 1
            return True
        except (BrokenPipeError, OSError):
            return False

    def stop(self):
        """Stop the encoder before closing pipes so a blocked write cannot hang cleanup."""
        self._stopped.set()
        with self._ready:
            self._ready.notify_all()
        if self.proc.poll() is None:
            self.proc.terminate()
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        for close in (self.proc.stdin.close, lambda: os.close(self._audio_fd)):
            try:
                close()
            except OSError:
                pass
        self._pump.join(timeout=1)
        for thread in self._relay:
            thread.join(timeout=1)
        if self._watchdog is not None:
            self._watchdog.join(timeout=1)
        if self.delay > 0:
            self._socket.close()
        for pipe in (self.proc.stdout, self.proc.stderr):
            if pipe is not None:
                pipe.close()


class OBSFeedDaemon(Daemon):
    """Encode the live frame ring to UDP while OBS is open."""

    def __init__(self, dman):
        """Read the feed settings and start the feed process."""
        config = dman.context.config

        def loop(ns, uns, ring, audio_ring, native_ring, mode, port, bitrate, delay_ms):
            """Feed frames to ffmpeg whenever OBS is running; idle otherwise."""
            # Runs at the bot's normal priority, above the web feed, since OBS
            # depends on it; only NXBT outranks it.
            feed = None
            feed_mode_now = None
            last_seq = 0
            last_sent_ns = 0
            next_poll = 0.0
            retry_at = 0.0
            wanted = False
            while ns.run:
                now = time.monotonic()
                if now >= next_poll:
                    next_poll = now + OBS_POLL_SECONDS
                    # After an encoder failure, wait before trying again
                    wanted = now >= retry_at and (mode == "always" or obs_running())
                native = bool(getattr(uns, "capture_native", False))
                requested = (
                    setting(uns, "obs_fps"),
                    setting(uns, "obs_height"),
                    native,
                )
                if feed is not None and wanted and requested != feed_mode_now:
                    # The resolution or frame rate changed: restart the encoder
                    feed.stop()
                    feed = None
                if wanted and feed is None:
                    feed_mode_now = requested
                    last_seq = 0  # each ring counts its own frames
                    last_sent_ns = 0
                    fps, height, native = requested
                    feed = Feed(
                        port,
                        fps,
                        bitrate,
                        audio_ring,
                        delay_ms,
                        height,
                        native=native,
                        source_ring=native_ring if native else ring,
                    )
                    uns.obs_feeding = True
                    uns.obs_feed_generation = time.monotonic()
                    logger.notice(
                        "Streaming %sp%s %s video and audio to `udp://127.0.0.1:%s`",
                        height,
                        fps,
                        "NV12" if native else "BGR",
                        port,
                    )
                if not wanted and feed is not None:
                    feed.stop()
                    feed = None
                    uns.obs_feeding = False
                    logger.info("OBS closed; stopped the feed.")
                if feed is None:
                    # Nothing to feed; wake up often enough to notice OBS or shutdown
                    time.sleep(0.5)
                    continue
                if feed.proc.poll() is not None:
                    logger.warning(
                        "OBS feed encoder exited: %s",
                        feed.proc.stderr.read().decode(errors="replace").strip(),
                    )
                    feed.stop()
                    feed = None
                    uns.obs_feeding = False
                    wanted = False
                    retry_at = time.monotonic() + 10
                    continue
                claim = (native_ring if feed_mode_now[2] else ring).wait_frame(
                    last_seq, 0.25
                )
                if claim is None:
                    continue
                last_seq = claim.seq
                try:
                    # The card may run faster than this feed; capture times jitter
                    if claim.time_ns - last_sent_ns >= 0.8e9 / feed_mode_now[0]:
                        last_sent_ns = claim.time_ns
                        feed.write_claim(claim)
                finally:
                    claim.release()
            if feed is not None:
                feed.stop()
                uns.obs_feeding = False

        super().__init__(
            dman,
            feed_mode(config.get("obs_feed", True)),
            int(config.get("obs_feed_port", 5000)),
            str(config.get("obs_feed_bitrate", "50M")),
            max(0, int(config.get("obs_feed_delay_ms", 0))),
            ring=True,
            audio_ring=True,
            native_ring=True,
        )
        self.loop = loop
        self.start()


def feed_mode(value):
    """Normalize `obs_feed`: "auto" (follow OBS), "always", or "off"."""
    if isinstance(value, str):
        value = value.strip().lower()
        if value == "always":
            return "always"
        if value in ("false", "off", "no", "0"):
            return "off"
        return "auto"
    return "auto" if value else "off"
