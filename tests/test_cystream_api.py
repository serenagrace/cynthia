from types import SimpleNamespace

from fastapi.testclient import TestClient

from cynthia.daemons.cystream import create_app
from cynthia.utils.drive import Drive


def test_cystream_api_status_viewers_and_video_page(tmp_path):
    (tmp_path / "user_status.json").write_text('{"name": "test stream"}')
    (tmp_path / "site" / "html").mkdir(parents=True)
    (tmp_path / "site" / "html" / "video_feed.html").write_text(
        "<html>test video page</html>"
    )
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
    assert page_response.text == "<html>test video page</html>"


def test_cystream_api_returns_empty_status_for_invalid_json(tmp_path):
    (tmp_path / "user_status.json").write_text("{invalid")
    (tmp_path / "site" / "html").mkdir(parents=True)
    (tmp_path / "site" / "html" / "video_feed.html").write_text("page")
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
    (tmp_path / "site" / "html").mkdir(parents=True)
    (tmp_path / "site" / "html" / "video_feed.html").write_text("page")
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
