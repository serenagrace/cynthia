import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "cyclient", Path(__file__).parent.parent / "tools" / "cyclient.py"
)
cyclient = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cyclient)


def test_service_urls_share_configured_host_and_protocol():
    assert cyclient.API_URL == "https://serenegrace.io/api/user_status"
    assert cyclient.FEED_URL == "https://serenegrace.io/video_feed"


def test_start_is_shifted_by_correction():
    data = {"timestamps": {"start": 1000, "correction": 500}}
    assert cyclient.corrected_start(data) == 1500


def test_start_without_correction_or_timestamps():
    assert cyclient.corrected_start({"timestamps": {"start": 1000}}) == 1000
    assert cyclient.corrected_start({"timestamps": {"start": None}}) is None
    assert cyclient.corrected_start({}) is None


def test_build_presence_uses_corrected_start_and_defaults():
    presence = cyclient.build_presence(
        {"name": "Game", "timestamps": {"start": 10, "correction": 5}}
    )
    assert presence["start"] == 15
    assert presence["activity_type"] == "playing"
    assert presence["large_image"] is None


def test_build_presence_skips_empty_status():
    assert cyclient.build_presence({}) is None
    assert cyclient.build_presence({"name": ""}) is None


def test_update_presence_clears_when_status_is_empty():
    class FakeRPC:
        def __init__(self):
            self.cleared = False

        def clear(self):
            self.cleared = True

        def update(self, **kwargs):
            raise AssertionError("empty status must not publish activity")

    rpc = FakeRPC()

    cyclient.update_presence(rpc, {}, {})

    assert rpc.cleared
