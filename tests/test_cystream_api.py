import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from cynthia.daemons.cystream import create_app, spoken_duration
from cynthia.utils.drive import Drive


def test_cystream_api_status_viewers_and_video_page(tmp_path):
    (tmp_path / "user_status.json").write_text('{"name": "test stream"}')
    ns = SimpleNamespace(run=True)
    uns = SimpleNamespace()
    app = create_app(Drive(tmp_path), ns, uns, None)

    with TestClient(app) as client:
        status_response = client.get("/api/user_status")
        viewer_response = client.get("/api/viewers")
        page_response = client.get("/video_feed")

    assert status_response.status_code == 200
    assert status_response.json() == {"name": "test stream"}
    assert viewer_response.json() == {"viewers": 0}
    assert page_response.status_code == 200
    assert 'id="feed"' in page_response.text
    assert 'class="controller-pad"' in page_response.text
    assert 'id="DPAD_UP"' in page_response.text


def test_cystream_api_returns_empty_status_for_invalid_json(tmp_path):
    (tmp_path / "user_status.json").write_text("{invalid")
    app = create_app(
        Drive(tmp_path),
        SimpleNamespace(run=True),
        SimpleNamespace(),
        None,
    )

    with TestClient(app) as client:
        response = client.get("/api/user_status")

    assert response.status_code == 200
    assert response.json() == {}


def test_cystream_stream_endpoint_is_multipart(tmp_path):
    ns = SimpleNamespace(run=False)
    app = create_app(
        Drive(tmp_path),
        ns,
        SimpleNamespace(),
        None,
    )

    with TestClient(app) as client:
        response = client.get("/api/stream_endpoint")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "multipart/x-mixed-replace; boundary=frame"
    )
    assert app.state.viewers["count"] == 0


def test_cystream_api_activity_stats(tmp_path):
    (tmp_path / "activity_stats.json").write_text('{"bot_started": 1}')
    app = create_app(
        Drive(tmp_path),
        SimpleNamespace(run=True),
        SimpleNamespace(),
        None,
    )

    with TestClient(app) as client:
        response = client.get("/api/activity_stats")

    assert response.json() == {"bot_started": 1}


@pytest.mark.parametrize(
    "seconds, text",
    [
        (0, "0 minutes and 0 seconds"),
        (61, "1 minute and 1 second"),
        (59 * 60 + 59, "59 minutes and 59 seconds"),
        (3600 + 120 + 30, "1 hour and 2 minutes"),
        (2 * 86400 + 3600 + 59, "2 days and 1 hour"),
        (86400, "1 day and 0 hours"),
    ],
)
def test_spoken_duration(seconds, text):
    assert spoken_duration(seconds) == text


@pytest.mark.parametrize(
    "stats, text",
    [
        ({"hunt": "cresselia", "self_encounter": False}, "hunting shiny Cresselia"),
        (
            {"hunt": "mew", "self_encounter": True, "status": "x"},
            "trying to get a shiny Mew",
        ),
        ({"status": "Breeding Eevees for a Sylveon"}, "Breeding Eevees for a Sylveon"),
        ({}, "not doing anything in particular right now"),
    ],
)
def test_streamelements_description_is_plain_text(tmp_path, stats, text):
    (tmp_path / "activity_stats.json").write_text(json.dumps(stats))
    app = create_app(
        Drive(tmp_path), SimpleNamespace(run=True), SimpleNamespace(), None
    )

    with TestClient(app) as client:
        response = client.get("/api/streamelements/description")

    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == text


def test_streamelements_uptime_is_plain_text(tmp_path):
    started_ms = (time.time() - (3 * 3600 + 5 * 60 + 10)) * 1000
    (tmp_path / "activity_stats.json").write_text(
        json.dumps({"bot_started": started_ms})
    )
    app = create_app(
        Drive(tmp_path), SimpleNamespace(run=True), SimpleNamespace(), None
    )

    with TestClient(app) as client:
        response = client.get("/api/streamelements/uptime")
        (tmp_path / "activity_stats.json").write_text("{}")
        missing = client.get("/api/streamelements/uptime")
        online = client.get("/api/streamelements/online")

    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "has been running for 3 hours and 5 minutes"
    assert missing.text == "isn't running right now"
    assert online.headers["content-type"].startswith("text/plain")
    assert online.text == "True"


def test_cystream_status_apis_return_empty_data_when_drive_disabled():
    app = create_app(
        Drive(None),
        SimpleNamespace(run=True),
        SimpleNamespace(),
        None,
    )

    with TestClient(app) as client:
        status_response = client.get("/api/user_status")
        stats_response = client.get("/api/activity_stats")

    assert status_response.status_code == 200
    assert status_response.json() == {}
    assert stats_response.status_code == 200
    assert stats_response.json() == {}


def test_cystream_api_inputs(tmp_path):
    app = create_app(
        Drive(tmp_path),
        SimpleNamespace(run=True),
        SimpleNamespace(pressed_buttons=["A", "DPAD_UP"]),
        None,
    )

    with TestClient(app) as client:
        response = client.get("/api/inputs")

    assert response.json() == {"pressed": ["A", "DPAD_UP"]}


def test_cystream_delayed_inputs_and_ssim_lag_the_web_stream(tmp_path):
    import time

    uns = SimpleNamespace(pressed_buttons=["A"], ssim_scores=[("home", 0.9)])
    app = create_app(
        Drive(tmp_path), SimpleNamespace(run=True), uns, None, video_delay_ms=300
    )

    with TestClient(app) as client:
        time.sleep(0.5)
        uns.pressed_buttons = ["B"]
        uns.ssim_scores = [("map", 0.8)]
        live = client.get("/api/inputs").json()
        lagged = client.get("/api/inputs?delayed=true").json()
        lagged_ssim = client.get("/api/ssim_data?delayed=true").json()
        time.sleep(0.5)
        caught_up = client.get("/api/inputs?delayed=true").json()

    assert live == {"pressed": ["B"]}
    assert lagged == {"pressed": ["A"]}
    assert lagged_ssim["scores"][0]["scene"] == "home"
    assert caught_up == {"pressed": ["B"]}


def test_cystream_obs_feed_inputs_use_the_obs_delay(tmp_path):
    import time

    uns = SimpleNamespace(pressed_buttons=["A"], ssim_scores=[("home", 0.9)])
    app = create_app(
        Drive(tmp_path),
        SimpleNamespace(run=True),
        uns,
        SimpleNamespace(seq=0, dropped=0, last_time_ns=0),
        video_delay_ms=100,
        obs_delay_ms=600,
    )

    with TestClient(app) as client:
        time.sleep(0.8)
        uns.pressed_buttons = ["B"]
        uns.ssim_scores = [("map", 0.8)]
        time.sleep(0.3)
        web = client.get("/api/inputs?delayed=true").json()
        obs = client.get("/api/inputs?delayed=true&feed=obs").json()
        obs_ssim = client.get("/api/ssim_data?delayed=true&feed=obs").json()
        uns.obs_overlay_sync = {"delay_ms": 100, "at": time.monotonic()}
        measured = client.get("/api/inputs?delayed=true&feed=obs").json()
        measured_ssim = client.get("/api/ssim_data?delayed=true&feed=obs").json()
        measured_delay = client.get("/api/stream_stats").json()["obs_overlay_delay_ms"]
        web_after = client.get("/api/inputs?delayed=true").json()
        uns.obs_overlay_sync["at"] -= 31
        fallback = client.get("/api/inputs?delayed=true&feed=obs").json()

    assert web == {"pressed": ["B"]}
    assert obs == {"pressed": ["A"]}
    assert obs_ssim["scores"][0]["scene"] == "home"
    assert measured == {"pressed": ["B"]}
    assert measured_ssim["scores"][0]["scene"] == "map"
    assert measured_delay == 100
    assert web_after == web
    assert fallback == obs


def test_jpeg_cache_evicts_least_recently_used_over_budget():
    from cynthia.daemons.cystream import JpegCache

    cache = JpegCache(budget=10)
    cache.put(1, b"aaaa")
    cache.put(2, b"bbbb")
    assert cache.get(1) == b"aaaa"
    cache.put(3, b"cccc")

    assert cache.get(2) is None
    assert cache.get(1) == b"aaaa"
    assert cache.get(3) == b"cccc"


def test_cystream_encodes_ring_frames_for_viewers_and_reuses_cache(tmp_path):
    import threading

    from cynthia.daemons.frames import FrameRing

    ring = FrameRing((72, 128, 3))
    ns = SimpleNamespace(run=True)
    app = create_app(Drive(tmp_path), ns, SimpleNamespace(), ring)
    try:
        for n in range(2):
            slot = ring.begin_write()
            ring.view(slot)[:] = 7
            ring.end_write(slot, (n + 1) * 10**9, 99)
        with TestClient(app) as client:
            # TestClient buffers the whole body, so end the stream from a timer
            timer = threading.Timer(1.5, lambda: setattr(ns, "run", False))
            timer.start()
            chunk = client.get("/api/stream_endpoint").content
            timer.cancel()
        assert b"image/jpeg" in chunk
        assert app.state.cache.misses == 1
    finally:
        ring.close(unlink=True)


def test_cystream_audio_stream_encodes_ring_pcm_and_reports_sync(tmp_path):
    import threading

    from cynthia.daemons.frames import AudioRing, FrameRing

    ring = FrameRing((72, 128, 3))
    audio = AudioRing(seconds=2)
    ns = SimpleNamespace(run=True)
    app = create_app(Drive(tmp_path), ns, SimpleNamespace(), ring, audio)
    stop = threading.Timer(1.5, lambda: setattr(ns, "run", False))
    try:
        with TestClient(app) as client:
            assert client.get("/api/sync").json()["video_latency_ms"] > 0
            stop.start()
            response = client.get("/api/audio_stream")
        assert response.headers["content-type"] == "audio/mpeg"
        # Silence fills in when the capture ring is empty, so MP3 data still flows
        assert len(response.content) > 1000
        assert audio.total == 0
    finally:
        stop.cancel()
        ring.close(unlink=True)
        audio.close()


def test_cystream_audio_stream_unavailable_without_ring(tmp_path):
    ns = SimpleNamespace(run=True)
    app = create_app(Drive(tmp_path), ns, SimpleNamespace(), None)

    with TestClient(app) as client:
        assert client.get("/api/audio_stream").status_code == 503


def test_cystream_holds_video_back_by_the_configured_delay(tmp_path):
    import threading
    import time

    from cynthia.daemons.frames import FrameRing

    def stream(delay_ms):
        ring = FrameRing((72, 128, 3))
        ns = SimpleNamespace(run=True)
        app = create_app(
            Drive(tmp_path), ns, SimpleNamespace(), ring, video_delay_ms=delay_ms
        )
        try:
            slot = ring.begin_write()
            ring.view(slot)[:] = 7
            ring.end_write(slot, time.time_ns(), 99)
            with TestClient(app) as client:
                timer = threading.Timer(1.5, lambda: setattr(ns, "run", False))
                timer.start()
                body = client.get("/api/stream_endpoint").content
                timer.cancel()
                sync = client.get("/api/sync").json()["video_latency_ms"]
            return body, sync
        finally:
            ring.close(unlink=True)

    held, sync = stream(5000)
    assert b"image/jpeg" not in held
    assert sync >= 5000
    released, _ = stream(0)
    assert b"image/jpeg" in released


def test_cystream_stream_stats_report_counters(tmp_path):
    import threading

    from cynthia.daemons.frames import FrameRing

    ring = FrameRing((72, 128, 3))
    ns = SimpleNamespace(run=True)
    app = create_app(Drive(tmp_path), ns, SimpleNamespace(), ring, video_delay_ms=0)
    try:
        slot = ring.begin_write()
        ring.view(slot)[:] = 7
        ring.end_write(slot, 10**9, 99)
        with TestClient(app) as client:
            timer = threading.Timer(1.5, lambda: setattr(ns, "run", False))
            timer.start()
            client.get("/api/stream_endpoint")
            timer.cancel()
            stats = client.get("/api/stream_stats").json()
        assert stats["capture_seq"] == 1
        assert stats["encoded_frames"] == 1 and stats["sent_frames"] == 1
        assert stats["cache_misses"] == 1 and stats["jpeg_kb"] > 0
        assert stats["audio"]["listeners"] == 0
    finally:
        ring.close(unlink=True)
