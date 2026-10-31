from types import SimpleNamespace

from fastapi.testclient import TestClient

from cynthia.daemons.cystream import create_app
from cynthia.utils.drive import Drive


def test_cystream_api_status_viewers_and_video_page(tmp_path):
    (tmp_path / "user_status.json").write_text('{"name": "test stream"}')
    ns = SimpleNamespace(run=True, uvc_time=0)
    uns = SimpleNamespace(fbptr=None)
    app = create_app(Drive(tmp_path), ns, uns, [None, None])

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
        SimpleNamespace(run=True, uvc_time=0),
        SimpleNamespace(fbptr=None),
        [None, None],
    )

    with TestClient(app) as client:
        response = client.get("/api/user_status")

    assert response.status_code == 200
    assert response.json() == {}


def test_cystream_stream_endpoint_is_multipart_and_resets_frame_hash(tmp_path):
    ns = SimpleNamespace(run=False, uvc_time=0, uvc_hash=10)
    app = create_app(
        Drive(tmp_path),
        ns,
        SimpleNamespace(fbptr=None),
        [None, None],
    )

    with TestClient(app) as client:
        response = client.get("/api/stream_endpoint")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "multipart/x-mixed-replace; boundary=frame"
    )
    assert ns.uvc_hash == -1
    assert app.state.viewers["count"] == 0


def test_cystream_api_activity_stats(tmp_path):
    (tmp_path / "activity_stats.json").write_text('{"bot_started": 1}')
    app = create_app(
        Drive(tmp_path),
        SimpleNamespace(run=True, uvc_time=0),
        SimpleNamespace(fbptr=None),
        [None, None],
    )

    with TestClient(app) as client:
        response = client.get("/api/activity_stats")

    assert response.json() == {"bot_started": 1}


def test_cystream_status_apis_return_empty_data_when_drive_disabled():
    app = create_app(
        Drive(None),
        SimpleNamespace(run=True, uvc_time=0),
        SimpleNamespace(fbptr=None),
        [None, None],
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
        SimpleNamespace(run=True, uvc_time=0),
        SimpleNamespace(fbptr=None, pressed_buttons=["A", "DPAD_UP"]),
        [None, None],
    )

    with TestClient(app) as client:
        response = client.get("/api/inputs")

    assert response.json() == {"pressed": ["A", "DPAD_UP"]}


def test_cystream_audio_stream_unavailable_without_device(tmp_path):
    app = create_app(
        Drive(tmp_path),
        SimpleNamespace(run=True, uvc_time=0),
        SimpleNamespace(fbptr=None),
        [None, None],
    )

    with TestClient(app) as client:
        response = client.get("/api/audio_stream")

    assert response.status_code == 503


def test_cystream_audio_stream_proxies_ffmpeg_output(tmp_path, monkeypatch):
    import asyncio

    real_exec = asyncio.create_subprocess_exec

    async def fake_exec(*args, **kwargs):
        assert args[0] == "ffmpeg" and "test_dev" in args
        return await real_exec("printf", "ID3audio", **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    app = create_app(
        Drive(tmp_path),
        SimpleNamespace(run=True, uvc_time=0),
        SimpleNamespace(fbptr=None),
        [None, None],
        "test_dev",
    )

    with TestClient(app) as client:
        response = client.get("/api/audio_stream")

    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == b"ID3audio"
