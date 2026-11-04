"""Measure OBS video age and keep its input and scene overlays on that timeline."""

import asyncio
import logging
import time
from collections import deque
from statistics import median

import cv2
import numpy
from discord.ext import commands, tasks

from cynthia.utils.obs import OBSError
from cynthia.utils.obslayout import OBS_SYNC_MAX_DELAY_MS, VIDEO_SOURCE

logger = logging.getLogger(__name__)

SAMPLE_SECONDS = 1 / 30
CHECK_SECONDS = 5
THUMB_SIZE = (96, 54)
MATCH_ERROR = 6.0
MATCH_MARGIN = 0.75
MATCH_SPREAD_SECONDS = 0.25
CONFIRM_SAMPLES = 3
DEADBAND_MS = 100
MAX_STEP_MS = 250


def thumbnail(frame):
    """Reduce a BGR capture or screenshot to a small grayscale comparison image."""
    small = cv2.resize(frame, THUMB_SIZE, interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(numpy.float32)


def match_delay(samples, encoded_image, now):
    """Return video age in milliseconds only for an unambiguous recent match.

    Similar images from widely separated times (a still screen or a repeating
    macro) cannot identify a playback timestamp and must not steer the delay.
    """
    if not samples:
        return None
    frame = cv2.imdecode(numpy.frombuffer(encoded_image, numpy.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        return None
    target = thumbnail(frame)
    stamps = numpy.array([stamp for stamp, _ in samples])
    errors = numpy.array([numpy.abs(image - target).mean() for _, image in samples])
    best = int(errors.argmin())
    if errors[best] > MATCH_ERROR:
        return None
    matches = stamps[errors <= errors[best] + MATCH_MARGIN]
    if matches.max() - matches.min() > MATCH_SPREAD_SECONDS:
        return None
    # A match at the edge might have an indistinguishable occurrence outside our
    # history. Wait for it to be surrounded by samples before trusting it.
    if best == 0 or best == len(samples) - 1:
        return None
    delay_ms = (now - stamps[best]) * 1000
    return delay_ms if 0 <= delay_ms <= OBS_SYNC_MAX_DELAY_MS else None


class OverlaySyncCog(commands.Cog):
    """Adjust only OBS overlays, using measured video rather than guessed clock drift."""

    def __init__(self, bot):
        """Keep bounded thumbnail history and require several consistent measurements."""
        self.bot = bot
        self.frames = deque(
            maxlen=int(OBS_SYNC_MAX_DELAY_MS / 1000 / SAMPLE_SECONDS) + 20
        )
        self.estimates = deque(maxlen=CONFIRM_SAMPLES)
        self.last_seq = 0
        self.last_cursor = None
        self.generation = None
        self.delay_ms = None
        self.active = False

    async def cog_load(self):
        """Start the sampler and checker unless automatic synchronization is disabled."""
        if self.bot.config.get("obs_auto_sync", True):
            self.sample.start()
            self.check.start()

    async def cog_unload(self):
        """Stop background work and restore the configured fallback delay."""
        self.sample.cancel()
        self.check.cancel()
        self.reset()

    def reset(self):
        """Discard measurements when the source changes, stops, or disconnects."""
        self.active = False
        self.frames.clear()
        self.estimates.clear()
        self.last_cursor = None
        self.delay_ms = None
        try:
            self.bot.dman.uns.obs_overlay_sync = None
        except (EOFError, OSError):
            pass

    def capture(self):
        """Copy a tiny ring image, releasing its slot before any OBS request."""
        claim = self.bot.dman.ring.wait_frame(self.last_seq, 0)
        if claim is None:
            return None
        try:
            age = (time.time_ns() - claim.time_ns) / 1e9
            if not 0 <= age < 1:
                return None
            return claim.seq, time.monotonic() - age, thumbnail(claim.frame)
        finally:
            claim.release()

    @tasks.loop(seconds=SAMPLE_SECONDS)
    async def sample(self):
        """Sample live capture without blocking Discord or retaining full video frames."""
        if not self.active:
            return
        try:
            captured = await asyncio.to_thread(self.capture)
            if captured is not None and self.active:
                self.last_seq, stamp, image = captured
                self.frames.append((stamp, image))
        except (EOFError, OSError):
            self.reset()
        except Exception:
            logger.exception("Couldn't sample capture for OBS overlay synchronization.")

    def observe(self, delay_ms):
        """Confirm stable measurements and slew toward them without timing jitter."""
        if delay_ms is None:
            self.estimates.clear()
            return
        self.estimates.append(delay_ms)
        if len(self.estimates) < CONFIRM_SAMPLES:
            return
        if max(self.estimates) - min(self.estimates) > MATCH_SPREAD_SECONDS * 1000:
            return
        target = median(self.estimates)
        current = self.delay_ms
        if current is None:
            current = max(
                0,
                float(self.bot.config.get("obs_feed_delay_ms", 0))
                + float(self.bot.config.get("obs_overlay_lag_ms", 0)),
            )
        if abs(target - current) < DEADBAND_MS:
            self.delay_ms = current
            return
        self.delay_ms = current + max(-MAX_STEP_MS, min(MAX_STEP_MS, target - current))
        logger.info(
            "OBS overlay delay %.0f -> %.0f ms (measured video age %.0f ms).",
            current,
            self.delay_ms,
            target,
        )

    @tasks.loop(seconds=CHECK_SECONDS)
    async def check(self):
        """Match OBS's media source to capture history and publish a fresh correction."""
        obs = getattr(self.bot, "obs", None)
        if obs is None:
            return
        try:
            status = await asyncio.to_thread(obs.status)
            if not (status["streaming"] or status["recording"]):
                self.reset()
                return
            media = await asyncio.to_thread(
                obs.call, "get_media_input_status", VIDEO_SOURCE
            )
            generation = getattr(self.bot.dman.uns, "obs_feed_generation", None)
            if media.media_state != "OBS_MEDIA_STATE_PLAYING":
                self.reset()
                return
            if generation != self.generation or (
                self.last_cursor is not None and media.media_cursor < self.last_cursor
            ):
                self.reset()
            self.generation = generation
            self.last_cursor = media.media_cursor
            self.active = True
            samples = tuple(self.frames)
            started = time.monotonic()
            # A larger JPEG avoids downscale aliasing without PNG's expensive encode.
            image = await asyncio.to_thread(
                obs.source_screenshot, VIDEO_SOURCE, 960, 540, "jpg"
            )
            finished = time.monotonic()
            # Slow screenshot calls have an uncertain timestamp; don't correct from them.
            delay = None
            if finished - started <= 0.25:
                delay = await asyncio.to_thread(
                    match_delay, samples, image, (started + finished) / 2
                )
            self.observe(delay)
            if self.delay_ms is not None:
                self.bot.dman.uns.obs_overlay_sync = {
                    "delay_ms": self.delay_ms,
                    "at": time.monotonic(),
                }
        except (OBSError, EOFError, OSError):
            self.reset()
        except Exception:
            self.reset()
            logger.exception("Couldn't synchronize the OBS overlays.")

    @sample.before_loop
    @check.before_loop
    async def before_loop(self):
        """Wait for the daemon manager and OBS cog to be available."""
        await self.bot.wait_until_ready()


async def setup(bot):
    """Register automatic OBS overlay synchronization."""
    await bot.add_cog(OverlaySyncCog(bot))
