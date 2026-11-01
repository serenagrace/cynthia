from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from cynthia.daemons.cystream import create_app
from cynthia.daemons.frames import AUDIO_BYTES_PER_SEC
from cynthia.daemons.obsfeed import audio_shortfall, audio_stretch
from cynthia.utils.drive import Drive
from cynthia.utils.obs import OBSControl
from cynthia.utils.obslayout import LayoutError, load_layout, normalize, source_name
from cynthia.utils.streamcfg import (
    CV_FPS,
    capture_mode,
    init_settings,
    parse_fps,
    parse_height,
)
from cynthia.utils.twitchchat import parse_privmsg


def uns(**values):
    state = dict(
        web_viewers=0,
        obs_active=False,
        web_fps=30,
        web_height=720,
        obs_fps=60,
        obs_height=1080,
    )
    return SimpleNamespace(**{**state, **values})


def test_capture_ignores_endpoints_that_are_not_running():
    state = uns()
    assert capture_mode(state) == (1080, 30)  # no 720p30 on the card
    state.web_viewers = 1
    state.web_height = 480
    assert capture_mode(state) == (1080, 30)  # CV needs 720p regardless
    state.obs_active = True
    assert capture_mode(state) == (1080, 60)
    state.obs_fps = 30
    state.obs_height = 720
    assert capture_mode(state) == (1080, 30)
    state.obs_fps = 60
    assert capture_mode(state) == (720, 60)


def test_web_viewers_never_raise_the_mode_over_a_running_obs():
    state = uns(web_viewers=2)
    state.web_height = 1080
    state.web_fps = 60
    assert capture_mode(state) == (1080, 60)  # web alone may ask for 60
    state.obs_height = 720
    state.obs_fps = 30
    state.obs_active = True
    assert capture_mode(state) == (1080, 30)
    assert CV_FPS == 30


def test_settings_parse_and_reject_bad_values():
    assert parse_height("720p") == 720
    assert parse_fps("60fps") == 60
    for bad in ("abc", "999"):
        with pytest.raises(ValueError):
            parse_height(bad)
    with pytest.raises(ValueError):
        parse_fps(45)
    state = SimpleNamespace()
    init_settings(state, {"web_fps": 99, "obs_height": "720"})
    assert (state.web_fps, state.obs_height, state.obs_fps) == (30, 720, 60)


def test_layout_validation(tmp_path):
    panes = normalize({"panes": [{"name": "inputs", "w": 0.5}]})
    assert panes[0]["kind"] == "inputs" and panes[0]["w"] == 0.5
    assert source_name({"name": "v", "kind": "video"}) == "Cynthia Feed"
    for bad in (
        {"panes": [{"name": "a", "kind": "nope"}]},
        {"panes": [{"name": "a", "kind": "chat", "x": 2}]},
        {"panes": [{"name": "a", "kind": "url"}]},
        {"panes": [{"name": "a", "kind": "chat"}, {"name": "a", "kind": "chat"}]},
    ):
        with pytest.raises(LayoutError):
            normalize(bad)
    assert load_layout(tmp_path / "missing.yaml")  # built-in default
    (tmp_path / "l.yaml").write_text("panes:\n- {name: stats, visible: false}\n")
    assert load_layout(tmp_path / "l.yaml")[0]["visible"] is False


class FakeOBS(OBSControl):
    """Records requests instead of talking to OBS."""

    def __init__(self, inputs=None):
        super().__init__(scene="Cynthia")
        self.calls = []
        self.inputs = inputs or {}

    def call(self, name, *args, **kwargs):
        self.calls.append((name, args))
        result = {
            "get_scene_list": SimpleNamespace(scenes=[{"sceneName": "Cynthia"}]),
            "get_video_settings": SimpleNamespace(
                base_width=1920, base_height=1080, fps_numerator=60, fps_denominator=1
            ),
            "get_input_list": SimpleNamespace(
                inputs=[
                    {"inputName": n, "inputKind": k} for n, k in self.inputs.items()
                ]
            ),
            "get_scene_item_list": SimpleNamespace(scene_items=[]),
            "create_input": SimpleNamespace(scene_item_id=7),
            "create_scene_item": SimpleNamespace(scene_item_id=8),
        }
        return result.get(name)


def test_apply_layout_creates_orders_and_prunes_sources():
    obs = FakeOBS({"Cynthia old": "browser_source", "Someone else": "browser_source"})
    panes = normalize(
        {
            "panes": [
                {"name": "video", "kind": "video"},
                {"name": "chat", "x": 0.5, "y": 0.5, "w": 0.5, "h": 0.5},
            ]
        }
    )
    assert obs.apply_layout(panes) == 2
    made = [c for c in obs.calls if c[0] == "create_input"]
    assert [c[1][1] for c in made] == ["Cynthia Feed", "Cynthia chat"]
    chat_settings = made[1][1][3]
    assert chat_settings["url"] == "http://127.0.0.1:8000/pane/chat"
    assert (chat_settings["width"], chat_settings["height"]) == (960, 540)
    assert ("remove_input", ("Cynthia old",)) in obs.calls
    assert ("remove_input", ("Someone else",)) not in obs.calls
    transform = [c for c in obs.calls if c[0] == "set_scene_item_transform"][1][1][2]
    assert (transform["positionX"], transform["positionY"]) == (960, 540)


def test_twitch_chat_parsing():
    line = "@color=#FF0000;display-name=Ash :ash!ash@ash.tmi.twitch.tv PRIVMSG #chan :gotta catch em"
    message = parse_privmsg(line)
    assert (message["user"], message["color"], message["text"]) == (
        "Ash",
        "#FF0000",
        "gotta catch em",
    )
    assert parse_privmsg(":tmi.twitch.tv 001 justinfan1 :Welcome") is None


def test_overlay_panes_and_chat_endpoint(tmp_path):
    from cynthia.daemons.frames import FrameRing

    ring = FrameRing((72, 128, 3))
    app = create_app(Drive(tmp_path), SimpleNamespace(run=True), uns(), ring)
    with TestClient(app) as client:
        inputs = client.get("/pane/inputs")
        assert inputs.status_code == 200 and 'id="DPAD_UP"' in inputs.text
        assert client.get("/pane/chat").status_code == 200
        assert client.get("/pane/nope").status_code == 404
        assert client.get("/api/twitch_chat").json() == {"messages": []}
        stats = client.get("/api/stream_stats").json()
    ring.close(unlink=True)
    assert (stats["web_fps"], stats["obs_height"], stats["cv_fps"]) == (30, 1080, 30)


def test_vbv_args_spread_keyframes_over_the_buffer():
    from cynthia.daemons.obsfeed import vbv_args

    assert vbv_args("8M", 0.25) == ["-maxrate", "8000000", "-bufsize", "2000000"]
    assert vbv_args("6000k", 0.5) == ["-maxrate", "6000000", "-bufsize", "3000000"]
    assert vbv_args("50M", None) == []


def test_native_nv12_feed_skips_conversion_unless_resizing():
    from cynthia.daemons.obsfeed import ffmpeg_command, video_filter

    assert video_filter(1080, native=True) == "null"
    assert video_filter(720, native=True).startswith("scale=1280:720")
    assert "out_color_matrix=bt709" in video_filter(1080, native=False)
    native = ffmpeg_command(5000, 60, "50M", native=True)
    assert native[native.index("-pix_fmt") + 1] == "nv12"
    assert native[native.index("-vf") + 1] == "null"
    legacy = ffmpeg_command(5000, 60, "50M")
    assert legacy[legacy.index("-pix_fmt") + 1] == "bgr24"


def test_native_nv12_frames_encode_through_nvenc_command():
    import shutil
    import subprocess

    import pytest

    from cynthia.daemons.obsfeed import ffmpeg_command

    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not installed")
    command = ffmpeg_command(5000, 30, "8M", native=True)
    command[-1:] = ["-"]
    command[command.index("-f", len(command) - 4) + 1] = "null"
    frame = bytes([16] * 1920 * 1080 + [128] * 1920 * 540)
    result = subprocess.run(command, input=frame * 3, capture_output=True)
    if b"nvenc" in result.stderr.lower() and result.returncode:
        pytest.skip("NVENC is unavailable")
    assert result.returncode == 0, result.stderr.decode()[-300:]


def test_audio_shortfall_ignores_jitter_and_pads_lasting_lag():
    assert (
        audio_shortfall(10.0, 10.0 * AUDIO_BYTES_PER_SEC - 0.1 * AUDIO_BYTES_PER_SEC)
        == 0
    )
    assert audio_shortfall(10.0, 11.0 * AUDIO_BYTES_PER_SEC) == 0

    pad = audio_shortfall(10.0, 9.0 * AUDIO_BYTES_PER_SEC)

    assert pad % 4 == 0
    behind = (
        10.0 * AUDIO_BYTES_PER_SEC - (9.0 * AUDIO_BYTES_PER_SEC + pad)
    ) / AUDIO_BYTES_PER_SEC
    assert 0 < behind < 0.05


def test_audio_stretch_lengthens_chunks_only_when_behind():
    chunk = bytes(4 * 1000)
    on_time = 10.0 * AUDIO_BYTES_PER_SEC

    assert audio_stretch(chunk, 10.0, on_time) == chunk
    assert audio_stretch(chunk, 10.0, on_time + 5) == chunk

    stretched = audio_stretch(chunk, 10.0, on_time - 0.1 * AUDIO_BYTES_PER_SEC)

    assert len(stretched) % 4 == 0
    assert len(chunk) < len(stretched) <= len(chunk) * 1.02


def test_obs_cog_unload_tolerates_stopped_daemon_manager():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import Mock

    from cynthia.bot.cogs.obs import OBSCog

    class DeadNamespace:
        def __setattr__(self, key, value):
            raise BrokenPipeError(32, "Broken pipe")

    cog = OBSCog.__new__(OBSCog)
    cog.bot = SimpleNamespace(dman=SimpleNamespace(uns=DeadNamespace()))
    cog.obs = Mock()
    cog.poll = Mock()

    asyncio.run(cog.cog_unload())

    cog.poll.cancel.assert_called_once()
    cog.obs.close.assert_called_once()


def test_obs_cog_poll_stops_when_daemon_manager_is_gone():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import Mock

    from cynthia.bot.cogs.obs import OBSCog

    class DeadNamespace:
        def __setattr__(self, key, value):
            raise BrokenPipeError(32, "Broken pipe")

    cog = OBSCog.__new__(OBSCog)
    cog.bot = SimpleNamespace(dman=SimpleNamespace(uns=DeadNamespace()))
    cog.obs = Mock()
    cog.obs.status.return_value = {"streaming": False, "recording": False}
    cog.was_connected = False
    cog.last_status = None
    cancel = Mock()

    async def run():
        cog.poll.cancel = cancel
        await cog.poll.coro(cog)

    asyncio.run(run())

    cancel.assert_called_once()
    assert not cog.was_connected
