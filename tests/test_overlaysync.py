import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import cv2
import numpy
import pytest

from cynthia.bot.cogs.overlaysync import OverlaySyncCog, match_delay, thumbnail
from cynthia.daemons.frames import FrameRing
from cynthia.utils.obs import OBSError
from cynthia.utils.obslayout import overlay_delay_ms


def image(seed):
    """Make deterministic, distinct low-frequency content like a moving game scene."""
    rng = numpy.random.default_rng(seed)
    small = rng.integers(30, 220, (27, 48, 3), dtype=numpy.uint8)
    return cv2.resize(small, (192, 108), interpolation=cv2.INTER_NEAREST)


def encoded(frame):
    """Encode an image exactly as the OBS screenshot API does."""
    return cv2.imencode(".png", frame)[1].tobytes()


def cog():
    """Build the cog with a fake OBS controller and no background Discord tasks."""
    obs = Mock()
    obs.status.return_value = {"streaming": True, "recording": False}
    obs.call.return_value = SimpleNamespace(
        media_state="OBS_MEDIA_STATE_PLAYING", media_cursor=10000
    )
    obs.source_screenshot.return_value = encoded(image(1))
    bot = SimpleNamespace(
        config={"obs_feed_delay_ms": 1000, "obs_overlay_lag_ms": 1700},
        dman=SimpleNamespace(uns=SimpleNamespace(obs_feed_generation=1)),
        obs=obs,
        wait_until_ready=AsyncMock(),
    )
    return OverlaySyncCog(bot)


def test_image_matching_measures_drift_in_both_directions():
    samples = [(i / 10, thumbnail(image(i))) for i in range(100)]
    screenshot = encoded(image(75))
    assert match_delay(samples, screenshot, 10) == pytest.approx(2500)
    assert match_delay(samples, screenshot, 11) == pytest.approx(3500)
    assert match_delay(samples, screenshot, 9) == pytest.approx(1500)
    compressed = cv2.imencode(".jpg", image(75), [cv2.IMWRITE_JPEG_QUALITY, 85])[1]
    assert match_delay(samples, compressed.tobytes(), 10) == pytest.approx(2500)


def test_matching_ignores_static_repeating_unrelated_and_out_of_range_images():
    samples = [(i / 10, thumbnail(image(i))) for i in range(100)]
    screenshot = encoded(image(75))
    assert match_delay(samples, encoded(image(200)), 10) is None
    assert match_delay(samples, b"not a PNG", 10) is None
    assert match_delay(samples, screenshot, 20) is None
    assert match_delay([], screenshot, 10) is None
    assert match_delay(samples, encoded(image(0)), 10) is None
    static = [(i / 10, thumbnail(image(75))) for i in range(100)]
    assert match_delay(static, screenshot, 10) is None
    samples[25] = (2.5, thumbnail(image(75)))
    assert match_delay(samples, screenshot, 10) is None


def test_correction_requires_consistent_matches_and_is_bounded():
    sync = cog()
    sync.observe(3500, now=0)
    sync.observe(3500, now=5)
    assert sync.delay_ms is None
    sync.observe(None, now=10)  # ambiguous still frames add no evidence
    sync.observe(3500, now=15)
    assert sync.delay_ms == 2950  # slew 250 ms, don't jump 800 ms at once
    sync.observe(5200, now=20)  # a lone outlier is outvoted
    assert sync.delay_ms == 3200
    sync.estimates.clear()
    for i in range(3):
        sync.observe(2000, now=25 + i * 5)
    assert sync.delay_ms == 2950  # correcting in the opposite direction
    sync.estimates.clear()
    for i in range(3):
        sync.observe(2900, now=40 + i * 5)
    assert sync.delay_ms == 2950  # ignore sub-100 ms jitter


def test_old_matches_expire_before_confirming():
    sync = cog()
    sync.observe(3500, now=0)
    sync.observe(3500, now=5)
    sync.observe(3500, now=70)
    assert sync.delay_ms is None


def test_capture_releases_ring_claim_and_preserves_capture_time():
    sync = cog()
    ring = FrameRing((108, 192, 3))
    sync.bot.dman.ring = ring
    try:
        assert sync.capture() is None
        slot = ring.begin_write()
        ring.view(slot)[:] = image(1)
        ring.end_write(slot, time.time_ns() - 200_000_000, 1)
        before = time.monotonic()
        seq, stamp, thumb = sync.capture()
        assert seq == 1
        assert before - 0.3 < stamp < before - 0.1
        assert thumb.shape == (54, 96)
        assert all(claims == 0 for claims in ring._claims)
    finally:
        ring.close(unlink=True)


def test_checker_publishes_matched_delay_and_resets_after_encoder_recreation():
    sync = cog()
    sync.generation = 1
    now = time.monotonic()
    sync.frames.extend((now - 5 + i / 10, thumbnail(image(i))) for i in range(50))
    sync.bot.obs.source_screenshot.return_value = encoded(image(15))

    async def run():
        for _ in range(3):
            await sync.check.coro(sync)

    asyncio.run(run())
    state = sync.bot.dman.uns.obs_overlay_sync
    assert state["delay_ms"] == pytest.approx(2950)
    assert time.monotonic() - state["at"] < 1
    assert sync.active
    sync.bot.dman.uns.obs_feed_generation = 2
    asyncio.run(sync.check.coro(sync))
    assert sync.bot.dman.uns.obs_overlay_sync is None
    assert not sync.frames


@pytest.mark.parametrize("failure", ["offline", "disconnected", "restarted"])
def test_checker_restores_fallback_when_obs_is_unavailable_or_restarts(failure):
    sync = cog()
    sync.delay_ms = 3500
    sync.last_cursor = 20000
    sync.generation = 1
    sync.bot.dman.uns.obs_overlay_sync = {"delay_ms": 3500, "at": time.monotonic()}
    if failure == "offline":
        sync.bot.obs.status.return_value = {"streaming": False, "recording": False}
    elif failure == "disconnected":
        sync.bot.obs.status.side_effect = OBSError("offline")
    asyncio.run(sync.check.coro(sync))
    assert sync.bot.dman.uns.obs_overlay_sync is None
    assert sync.delay_ms is None


def test_stale_cog_measurements_use_configured_fallback():
    state = SimpleNamespace(obs_overlay_sync=None)
    assert overlay_delay_ms(state, 2700) == 2700
    state.obs_overlay_sync = {"delay_ms": 3400, "at": time.monotonic()}
    assert overlay_delay_ms(state, 2700) == 3400
    state.obs_overlay_sync["at"] -= 31
    assert overlay_delay_ms(state, 2700) == 2700


def test_disabled_and_unloaded_cog_leave_no_sync_tasks():
    sync = cog()
    sync.sample = Mock()
    sync.check = Mock()
    sync.bot.config["obs_auto_sync"] = False
    asyncio.run(sync.cog_load())
    sync.sample.start.assert_not_called()
    sync.check.start.assert_not_called()
    asyncio.run(sync.cog_unload())
    sync.sample.cancel.assert_called_once()
    sync.check.cancel.assert_called_once()
    assert sync.bot.dman.uns.obs_overlay_sync is None
