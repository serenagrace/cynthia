from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from cynthia.daemons.cystream import app_version, create_app
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
from cynthia.utils.twitchchat import TwitchChat, parse_privmsg


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


def test_twitch_chat_drops_deleted_messages():
    chat = TwitchChat("chan")

    def say(nick, user_id, msg_id, text):
        chat.handle(
            f"@display-name={nick};id={msg_id};user-id={user_id} "
            f":{nick.lower()}!{nick.lower()}@x.tmi.twitch.tv PRIVMSG #chan :{text}"
        )

    def texts():
        return [m["text"] for m in chat.recent()]

    say("Ash", "1", "a1", "hi")
    say("Gary", "2", "g1", "smell ya")
    say("Ash", "1", "a2", "spam")
    say("Gary", "2", "g2", "later")

    chat.handle("@login=ash;target-msg-id=a2 :tmi.twitch.tv CLEARMSG #chan :spam")
    assert texts() == ["hi", "smell ya", "later"]
    assert set(chat.recent()[0]) == {"user", "color", "text", "time"}

    # A timeout or ban removes everything that user said
    chat.handle(
        "@ban-duration=600;target-user-id=2 :tmi.twitch.tv CLEARCHAT #chan :gary"
    )
    assert texts() == ["hi"]

    # /clear empties the pane
    chat.handle("@room-id=9 :tmi.twitch.tv CLEARCHAT #chan")
    assert texts() == []


def test_overlay_panes_and_chat_endpoint(tmp_path):
    from cynthia.daemons.frames import FrameRing

    ring = FrameRing((72, 128, 3))
    app = create_app(Drive(tmp_path), SimpleNamespace(run=True), uns(), ring)
    with TestClient(app) as client:
        inputs = client.get("/pane/inputs")
        assert inputs.status_code == 200 and 'id="DPAD_UP"' in inputs.text
        assert client.get("/pane/chat").status_code == 200
        assert client.get("/pane/nope").status_code == 404
        watermark = client.get("/pane/watermark").text
        assert "Cynthia (<!--VERSION-->)" not in watermark
        assert f"Cynthia ({app_version()})" in watermark
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
    cog.restart_task = None

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


def test_obs_cog_restarts_a_stream_before_twitchs_48_hour_cutoff(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    import cynthia.bot.cogs.obs as obs_module
    from cynthia.bot.cogs.obs import OBSCog

    monkeypatch.setattr(obs_module, "POLL_SECONDS", 0)
    states = iter([True, False])
    cog = OBSCog.__new__(OBSCog)
    cog.bot = SimpleNamespace(
        dman=SimpleNamespace(uns=SimpleNamespace()),
        config={"twitch_restart_hours": 24},
        messenger=SimpleNamespace(msg_owner=AsyncMock()),
    )
    cog.obs = Mock()
    cog.was_connected = True
    cog.last_status = None
    cog.restart_task = None
    live = {"streaming": True, "recording": False, "stream_seconds": 24 * 3600 - 2}

    async def run():
        cog.obs.status.return_value = live
        await cog.poll.coro(cog)
        assert cog.restart_task is None

        live["stream_seconds"] = 24 * 3600
        cog.obs.status.side_effect = [
            live,
            *({"streaming": s, "recording": False} for s in states),
        ]
        await cog.poll.coro(cog)
        task = cog.restart_task
        # A poll during the restart doesn't start a second one
        assert not cog.restart_due(live)
        await task

    asyncio.run(run())

    cog.obs.stop_stream.assert_called_once()
    cog.obs.start_stream.assert_called_once()
    text = cog.bot.messenger.msg_owner.await_args.args[0]
    assert text.startswith("🔁 Restarted the stream after 24 hours")
    cog.bot.config["twitch_restart_hours"] = 0
    assert not cog.restart_due(live)


def test_obs_cog_stops_a_stream_after_ten_minutes_without_signal():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from cynthia.bot.cogs.obs import OBSCog

    cog = OBSCog.__new__(OBSCog)
    uns = SimpleNamespace(ssim_scores=[("elgato_no_signal", 0.99), ("home", 0.2)])
    cog.bot = SimpleNamespace(
        dman=SimpleNamespace(uns=uns),
        config={},
        messenger=SimpleNamespace(msg_owner=AsyncMock()),
    )
    cog.obs = Mock()
    cog.restart_task = None
    cog.no_signal_since = None
    live = {"streaming": True}

    assert not cog.no_signal_due(live, 0)
    assert not cog.no_signal_due(live, 599)
    # The signal coming back restarts the count
    uns.ssim_scores = [("bdsp_run", 0.95)]
    assert not cog.no_signal_due(live, 600)
    uns.ssim_scores = [("elgato_no_signal", 0.99)]
    assert not cog.no_signal_due(live, 700)
    assert not cog.no_signal_due({"streaming": False}, 1000)
    assert not cog.no_signal_due(live, 1100)
    assert cog.no_signal_due(live, 1700)

    asyncio.run(cog.stop_for_no_signal())

    cog.obs.stop_stream.assert_called_once()
    assert cog.no_signal_since is None
    text = cog.bot.messenger.msg_owner.await_args.args[0]
    assert text.startswith("⏹️ Stopped the stream: no capture signal")
    cog.bot.config["twitch_no_signal_stop_minutes"] = 0
    assert not cog.no_signal_due(live, 5000)


def command_interaction(client):
    """A fake interaction whose followup sends are collected in `sent`."""
    sent = []

    async def defer(**kwargs):
        pass

    async def send(content=None, **kwargs):
        sent.append(kwargs.get("embed") or content)

    return sent, SimpleNamespace(
        client=client,
        response=SimpleNamespace(defer=defer),
        followup=SimpleNamespace(send=send),
    )


def test_twitchurl_embed_reports_live_state_and_always_links():
    import asyncio

    from cynthia.bot.applications.twitch import twitchurl

    class Api:
        authorized = True

        async def live_stream(self, login):
            if login == "serena":
                return {
                    "title": "Shiny hunting",
                    "game_name": "BDSP",
                    "viewer_count": 3,
                }

    def client(api=None, cog=None, login="serena"):
        return SimpleNamespace(
            twitch_api=api, get_cog=lambda name: cog, env={"TWITCH_CHANNEL": login}
        )

    obs = SimpleNamespace(obs=SimpleNamespace(status=lambda: {"streaming": False}))
    embeds = []
    for c in (client(Api()), client(Api(), login="other"), client(None, obs), client()):
        sent, inter = command_interaction(c)
        asyncio.run(twitchurl.callback(inter))
        embeds.append(sent[0])

    live, offline, obs_offline, unknown = embeds
    assert live.url == "https://twitch.tv/serena"
    assert live.description == "🔴 **Live now**\nhttps://twitch.tv/serena"
    assert {f.name: f.value for f in live.fields} == {
        "Title": "Shiny hunting",
        "Category": "BDSP",
        "Viewers": "3",
    }
    assert offline.description.startswith("⚫ Offline")
    assert offline.description.endswith("https://twitch.tv/other")
    assert obs_offline.description.startswith("⚫ Offline")
    assert unknown.description.startswith("Couldn't check")
    assert unknown.description.endswith("https://twitch.tv/serena")


def test_obs_show_embeds_the_screenshot_with_output_state():
    import asyncio

    from cynthia.bot.applications.stream import obs_show

    status = {
        "streaming": True,
        "stream_seconds": 3723,
        "recording": False,
        "record_seconds": 0,
    }
    control = SimpleNamespace(screenshot=lambda: b"png", status=lambda: status)
    client = SimpleNamespace(
        get_cog=lambda name: SimpleNamespace(obs=control),
        dman=SimpleNamespace(uns=SimpleNamespace(obs_height=1080, obs_fps=60)),
        config={},
    )
    files = []
    sent, inter = command_interaction(client)

    async def send(content=None, **kwargs):
        sent.append(kwargs.get("embed") or content)
        files.append(kwargs.get("file"))

    inter.followup.send = send
    asyncio.run(obs_show.callback(inter))

    embed = sent[0]
    assert embed.image.url == "attachment://obs.png"
    assert files[0].filename == "obs.png"
    assert {f.name: f.value for f in embed.fields} == {
        "Video mode": "1080p60",
        "Streaming": "🔴 1:02:03",
        "Recording": "No",
    }


def test_twitch_start_and_stop_wait_for_a_confirming_button_press():
    import asyncio

    from cynthia.bot.applications import twitch

    calls = []
    state = {"streaming": False}

    def status():
        return {
            "streaming": state["streaming"],
            "stream_seconds": 60,
            "bytes": 0,
            "total_frames": 1,
            "skipped_frames": 0,
            "congestion": 0.0,
            "reconnecting": False,
        }

    def start_stream():
        calls.append("start")
        state["streaming"] = True

    def stop_stream():
        calls.append("stop")
        state["streaming"] = False

    async def prepare():
        pass

    control = SimpleNamespace(
        status=status,
        start_stream=start_stream,
        stop_stream=stop_stream,
        set_stream_key=lambda *a: None,
    )
    client = SimpleNamespace(
        get_cog=lambda name: SimpleNamespace(obs=control, prepare=prepare),
        dman=SimpleNamespace(uns=SimpleNamespace()),
        config={},
        env={"TWITCH_STREAM_KEY": "k", "TWITCH_CHANNEL": "serena"},
    )

    def press(user_id):
        """A button interaction from `user_id`; returns it and its replies."""
        replies = []

        async def edit(**kwargs):
            replies.append(kwargs["view"])

        async def send_message(text, **kwargs):
            replies.append(text)

        response = SimpleNamespace(edit_message=edit, send_message=send_message)
        return replies, SimpleNamespace(
            client=client,
            user=SimpleNamespace(id=user_id),
            response=response,
            edit_original_response=edit,
        )

    def text(view):
        return " ".join(
            c.content for c in view.walk_children() if hasattr(c, "content")
        )

    async def ask(command):
        """Run a command and return the ConfirmView it sent."""
        sent = []

        async def defer(**kwargs):
            pass

        async def send(content=None, **kwargs):
            sent.append(kwargs.get("view") or content)

        await command.callback(
            SimpleNamespace(
                client=client,
                user=SimpleNamespace(id=1),
                response=SimpleNamespace(defer=defer),
                followup=SimpleNamespace(send=send),
            )
        )
        return sent[0]

    async def run():
        view = await ask(twitch.start)
        assert isinstance(view, twitch.ConfirmView) and calls == []
        replies, stranger = press(2)
        assert not await view.interaction_check(stranger)
        assert "Only whoever ran" in replies[0]
        replies, owner = press(1)
        await view.cancel(owner)
        assert calls == [] and "wasn't started" in text(replies[-1])

        view = await ask(twitch.start)
        replies, owner = press(1)
        assert await view.interaction_check(owner)
        await view.confirm(owner)
        assert calls == ["start"] and "Streaming to Twitch" in text(replies[-1])
        assert "https://twitch.tv/serena" in text(replies[-1])

        view = await ask(twitch.stop)
        assert calls == ["start"] and "Stop the Twitch stream?" in text(view)
        replies, owner = press(1)
        await view.confirm(owner)
        assert calls == ["start", "stop"] and "Stream stopped" in text(replies[-1])
        assert view.is_finished()

    asyncio.run(run())
