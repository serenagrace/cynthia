import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "cyclient", Path(__file__).parent.parent / "tools" / "cyclient.py"
)
cyclient = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cyclient)


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
