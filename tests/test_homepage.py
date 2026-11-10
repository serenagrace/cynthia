import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from cynthia.bot.cogs.twitchinfo import TwitchInfoCog
from cynthia.daemons.cystream import create_app
from cynthia.daemons.frames import FrameRing
from cynthia.utils.drive import Drive


@pytest.fixture
def homepage(tmp_path):
    ring = FrameRing((72, 128, 3))
    slot = ring.begin_write()
    ring.view(slot)[:] = 80
    ring.end_write(slot, time.time_ns(), 1)
    uns = SimpleNamespace(ssim_scores=[("switch_home_screen", 0.99)])
    ns = SimpleNamespace(run=True)
    app = create_app(Drive(tmp_path), ns, uns, ring, twitch_channel="test_channel")
    try:
        with TestClient(app) as client:
            yield client, ring, ns, uns, app
    finally:
        ring.close(unlink=True)


def test_homepage_capture_snapshot_does_not_create_viewers(homepage, monkeypatch):
    client, ring, ns, uns, app = homepage
    calls = []
    imencode = cv2.imencode

    def encode(*args):
        calls.append(True)
        return imencode(*args)

    monkeypatch.setattr("cynthia.site.homepage.cv2.imencode", encode)
    status = client.get("/api/homepage_status")
    assert status.json() == {
        "visible": True,
        "label": "Watch CYStream",
        "url": "/video_feed",
        "thumbnail": "/api/homepage_thumbnail",
    }
    assert status.headers["cache-control"] == "no-store"
    first = client.get(status.json()["thumbnail"])
    second = client.get("/api/homepage_thumbnail")
    assert first.status_code == 200
    assert first.headers["content-type"] == "image/jpeg"
    assert first.headers["cache-control"] == "no-store"
    assert first.content == second.content
    assert cv2.imdecode(np.frombuffer(first.content, np.uint8), 1).shape == (
        270,
        480,
        3,
    )
    assert calls == [True]
    assert app.state.viewers["count"] == 0
    assert getattr(uns, "web_viewers", 0) == 0
    assert app.state.cache.size == 0
    assert not any(ring._claims)
    assert client.get("/api/viewers").json() == {"viewers": 0}
    assert client.get("/video_feed").status_code == 200


@pytest.mark.parametrize("condition", ["no-signal", "stale", "future", "stopped"])
def test_homepage_hides_and_refuses_snapshot_for_unavailable_capture(
    homepage, condition
):
    client, ring, ns, uns, _ = homepage
    # A cached JPEG must not survive a no-signal or stale-state check.
    assert client.get("/api/homepage_thumbnail").status_code == 200
    uns.homepage_twitch = {
        "live": True,
        "channel": "test_channel",
        "checked_at": time.time(),
    }
    if condition == "no-signal":
        uns.ssim_scores = [("elgato_no_signal", 0.99)]
    elif condition == "stale":
        ring._last_time.value = time.time_ns() - 10_000_000_000
    elif condition == "future":
        ring._last_time.value = time.time_ns() + 10_000_000_000
    else:
        ns.run = False
    assert client.get("/api/homepage_status").json() == {"visible": False}
    assert client.get("/api/homepage_thumbnail").status_code == 503


@pytest.mark.parametrize(
    "state, twitch",
    [
        ({"live": True, "channel": "test_channel", "age": 1}, True),
        ({"live": False, "channel": "test_channel", "age": 1}, False),
        ({"live": True, "channel": "test_channel", "age": 90}, False),
        ({"live": True, "channel": "wrong_channel", "age": 1}, False),
        ({"live": True, "channel": "test_channel", "age": -30}, False),
        ({"live": True, "channel": "test_channel", "age": "invalid"}, False),
    ],
)
def test_homepage_prefers_only_fresh_verified_twitch(homepage, state, twitch):
    client, _, _, uns, _ = homepage
    age = state.pop("age")
    state["checked_at"] = time.time() - age if isinstance(age, int) else age
    uns.homepage_twitch = state
    uns.obs_active = True  # OBS streaming/recording alone must never imply Twitch.
    result = client.get("/api/homepage_status").json()
    assert result["url"] == (
        "https://www.twitch.tv/test_channel" if twitch else "/video_feed"
    )


def test_homepage_missing_capture_is_hidden():
    app = create_app(Drive(None), SimpleNamespace(run=True), SimpleNamespace(), None)
    with TestClient(app) as client:
        assert client.get("/api/homepage_status").json() == {"visible": False}
        assert client.get("/api/homepage_thumbnail").status_code == 503
        # FastAPI docs are intentionally not a hosted Markdown renderer.
        assert client.get("/docs/cynthia").status_code == 404


@pytest.mark.parametrize("stream", [None, {"type": ""}, {"type": "live"}])
def test_homepage_live_publisher_uses_twitch_not_obs(stream):
    cog = TwitchInfoCog.__new__(TwitchInfoCog)
    cog.api = SimpleNamespace(
        authorized=True, live_stream=AsyncMock(return_value=stream)
    )
    uns = SimpleNamespace()
    cog.bot = SimpleNamespace(
        env={"TWITCH_CHANNEL": "test_channel"}, dman=SimpleNamespace(uns=uns)
    )
    asyncio.run(cog.publish_live())
    assert uns.homepage_twitch["live"] is bool(stream and stream["type"] == "live")
    assert time.time() - uns.homepage_twitch["checked_at"] < 1
    cog.api.live_stream.assert_awaited_once_with("test_channel")


def test_homepage_live_publisher_clears_errors_and_missing_authorization():
    cog = TwitchInfoCog.__new__(TwitchInfoCog)
    cog.api = SimpleNamespace(
        authorized=True, live_stream=AsyncMock(side_effect=RuntimeError("offline"))
    )
    uns = SimpleNamespace(homepage_twitch={"live": True})
    cog.bot = SimpleNamespace(
        env={"TWITCH_CHANNEL": "test_channel"}, dman=SimpleNamespace(uns=uns)
    )
    asyncio.run(cog.publish_live())
    assert uns.homepage_twitch["live"] is False
    cog.api.authorized = False
    uns.homepage_twitch = {"live": True}
    asyncio.run(cog.publish_live())
    assert uns.homepage_twitch["live"] is False
    assert cog.api.live_stream.await_count == 1
