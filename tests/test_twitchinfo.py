import asyncio
import json
import os
import time
from types import SimpleNamespace

from aiohttp import web

import cynthia.utils.twitchapi as twitchapi
from cynthia.bot.cogs.twitchinfo import ChannelInfoTracker, TwitchInfoCog
from cynthia.utils.drive import Drive
from cynthia.utils.twitchapi import TwitchAPI


def confirmed(tracker, game, hunt, start):
    """Observe one detection twice, `confirm_seconds` apart."""
    tracker.observe(game, hunt, start)
    return tracker.observe(game, hunt, start + tracker.confirm_seconds)


def test_tracker_waits_for_a_steady_known_game():
    tracker = ChannelInfoTracker(60)

    assert tracker.observe("Pokémon Shining Pearl", "cresselia", 0) is None
    assert tracker.observe("Pokémon Shining Pearl", "cresselia", 59) is None
    # A trip to HOME restarts the wait
    assert tracker.observe(None, None, 60) is None
    assert tracker.observe("Pokémon Shining Pearl", "cresselia", 61) is None
    assert tracker.observe("Pokémon Shining Pearl", "cresselia", 121) == {
        "game": "Pokémon Shining Pearl",
        "hunt": "cresselia",
    }


def test_tracker_only_changes_the_channel_for_a_new_game_or_hunt():
    tracker = ChannelInfoTracker(
        60, {"game": "Pokémon Shining Pearl", "hunt": "cresselia"}
    )

    # Same game and hunt, e.g. after a restart or a manual edit on Twitch
    assert confirmed(tracker, "Pokémon Shining Pearl", "cresselia", 0) is None
    # Clearing the hunt, then setting the same hunt again
    assert confirmed(tracker, "Pokémon Shining Pearl", None, 100) is None
    assert confirmed(tracker, "Pokémon Shining Pearl", "cresselia", 200) is None
    # A different hunt in the same game
    assert confirmed(tracker, "Pokémon Shining Pearl", "giratina", 300) == {
        "game": "Pokémon Shining Pearl",
        "hunt": "giratina",
    }
    # A different game, with no hunt yet
    assert confirmed(tracker, "Pokémon Brilliant Diamond", None, 400) == {
        "game": "Pokémon Brilliant Diamond",
        "hunt": None,
    }
    tracker.mark_applied({"game": "Pokémon Brilliant Diamond", "hunt": None})
    # After a game change the next hunt is new, even if it was hunted before
    assert confirmed(tracker, "Pokémon Brilliant Diamond", "cresselia", 500) == {
        "game": "Pokémon Brilliant Diamond",
        "hunt": "cresselia",
    }


def make_cog(tmp_path, ns, hunt=None, api=None, config=None):
    cog = TwitchInfoCog.__new__(TwitchInfoCog)
    cog.bot = SimpleNamespace(
        dman=SimpleNamespace(running_daemons={"CVDaemon": SimpleNamespace(ns=ns)}),
        args=SimpleNamespace(hunt=hunt),
        drive=Drive(tmp_path),
        config=config or {},
    )
    cog.api = api
    cog.tracker = ChannelInfoTracker(60)
    return cog


def test_cog_only_detects_known_games_that_are_playing(tmp_path):
    ns = SimpleNamespace(
        playing=True, home=False, game="Pokémon Shining Pearl", self_encounter=True
    )
    cog = make_cog(tmp_path, ns, hunt="cresselia")

    assert cog.detected() == ("Pokémon Shining Pearl", "cresselia", True)
    ns.game = "Pokem0n Shnng Prl"
    assert cog.detected() == (None, None, False)
    ns.game, ns.home, ns.playing = "Pokémon Shining Pearl", True, False
    assert cog.detected() == (None, None, False)


def test_cog_apply_skips_an_unknown_category_and_saves_state(tmp_path):
    calls = []

    class FakeAPI:
        async def find_category(self, name):
            return None

        async def update_channel(self, game_id=None, title=None):
            calls.append((game_id, title))

    cog = make_cog(tmp_path, None, api=FakeAPI())
    change = {"game": "Pokémon Shining Pearl", "hunt": "cresselia"}

    asyncio.run(cog.apply(change, self_encounter=True))

    assert calls == [(None, "Looking for shiny Cresselia")]
    assert cog.tracker.applied == change
    assert json.loads((tmp_path / "twitch_channel.json").read_text()) == change


def test_cog_apply_uses_a_category_id_override(tmp_path):
    calls = []

    class FakeAPI:
        async def find_category(self, name):
            raise AssertionError("an id override needs no lookup")

        async def update_channel(self, game_id=None, title=None):
            calls.append((game_id, title))

    cog = make_cog(
        tmp_path,
        None,
        api=FakeAPI(),
        config={"twitch_categories": {"Pokémon Shining Pearl": "123"}},
    )

    asyncio.run(cog.apply({"game": "Pokémon Shining Pearl", "hunt": None}, False))

    assert calls == [("123", None)]


def test_twitch_api_refreshes_an_expired_token_and_updates_the_channel(
    tmp_path, monkeypatch
):
    seen = {}

    async def token(request):
        form = await request.post()
        seen["refresh"] = dict(form)
        return web.json_response(
            {
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 14000,
            }
        )

    async def validate(request):
        assert request.headers["Authorization"] == "OAuth new-access"
        return web.json_response(
            {"user_id": "42", "login": "serena", "scopes": ["clips:edit"]}
        )

    async def games(request):
        names = {"Pokémon Shining Pearl": [{"id": "999"}]}
        return web.json_response({"data": names.get(request.query["name"], [])})

    async def channels(request):
        seen["auth"] = request.headers["Authorization"]
        seen["client"] = request.headers["Client-Id"]
        seen["broadcaster"] = request.query["broadcaster_id"]
        seen["body"] = await request.json()
        return web.Response(status=204)

    async def clips(request):
        seen["clip"] = dict(request.query)
        return web.json_response(
            {"data": [{"id": "Clip", "edit_url": "https://twitch.tv/x/clip/Clip"}]},
            status=202,
        )

    async def streams(request):
        live = {"serena": [{"type": "live", "title": "Hi"}], "tester": [{"type": ""}]}
        return web.json_response({"data": live.get(request.query["user_login"], [])})

    async def run():
        app = web.Application()
        app.router.add_get("/helix/streams", streams)
        app.router.add_post("/oauth2/token", token)
        app.router.add_get("/oauth2/validate", validate)
        app.router.add_get("/helix/games", games)
        app.router.add_patch("/helix/channels", channels)
        app.router.add_post("/helix/clips", clips)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        monkeypatch.setattr(twitchapi, "AUTH_URL", f"http://127.0.0.1:{port}/oauth2")
        monkeypatch.setattr(twitchapi, "HELIX_URL", f"http://127.0.0.1:{port}/helix")
        try:
            api = TwitchAPI("client", "secret", Drive(tmp_path))
            api.tokens = {
                "access_token": "old-access",
                "refresh_token": "old-refresh",
                "expires_at": time.time() - 1,
                "user_id": "42",
            }
            found = await api.find_category("Pokémon Shining Pearl")
            missing = await api.find_category("Pokemon Shinning Pearl")
            await api.update_channel(found, "x" * 200)
            clip = await api.create_clip(title="Shiny Cresselia!")
            seen["live"] = [
                await api.live_stream(login) for login in ("serena", "tester", "nobody")
            ]
            return found, missing, clip
        finally:
            await runner.cleanup()

    found, missing, clip = asyncio.run(run())

    assert (found, missing) == ("999", None)
    assert seen["live"] == [{"type": "live", "title": "Hi"}, None, None]
    assert clip["edit_url"] == "https://twitch.tv/x/clip/Clip"
    assert seen["clip"] == {"broadcaster_id": "42", "title": "Shiny Cresselia!"}
    assert seen["refresh"] == {
        "client_id": "client",
        "client_secret": "secret",
        "grant_type": "refresh_token",
        "refresh_token": "old-refresh",
    }
    assert seen["auth"] == "Bearer new-access"
    assert seen["client"] == "client"
    assert seen["broadcaster"] == "42"
    assert seen["body"] == {"game_id": "999", "title": "x" * 140}
    stored = tmp_path / "twitch_token.json"
    assert json.loads(stored.read_text())["refresh_token"] == "new-refresh"
    assert os.stat(stored).st_mode & 0o777 == 0o600


def test_clipping_needs_a_new_authorization_without_the_clip_scope(tmp_path):
    from cynthia.utils.twitchapi import TwitchAuthError

    api = TwitchAPI("client", None, Drive(tmp_path))
    api.tokens = {"refresh_token": "r", "user_id": "42"}

    try:
        asyncio.run(api.create_clip())
    except TwitchAuthError as e:
        assert "/twitch auth" in str(e)
    else:
        raise AssertionError("expected TwitchAuthError")


def test_cog_clips_a_new_shiny_once_it_reaches_the_live_stream(tmp_path):
    from unittest.mock import AsyncMock, Mock

    clips = []

    class FakeAPI:
        async def create_clip(self, title=None, duration=None):
            clips.append(title)
            return {"id": "c", "edit_url": "https://twitch.tv/x/clip/c"}

    uns = SimpleNamespace(nxbt_daemon_stop=True)
    cog = make_cog(tmp_path, None, hunt="cresselia", api=FakeAPI())
    cog.bot.dman.uns = uns
    cog.bot.config = {"twitch_clip_delay_seconds": 0}
    assert cog.clip_delay() == 0
    cog.bot.config = {
        "obs_feed_delay_ms": 1000,
        "obs_overlay_lag_ms": 1700,
        "twitch_clip_delay_seconds": 10,
    }
    assert cog.clip_delay() == 12.7
    uns.obs_overlay_sync = {"delay_ms": 3400, "at": time.monotonic()}
    assert cog.clip_delay() == 13.4
    uns.obs_overlay_sync = None
    cog.bot.config = {"twitch_clip_delay_seconds": 0}
    cog.bot.obs = Mock(status=Mock(return_value={"streaming": True}))
    cog.bot.messenger = SimpleNamespace(msg_owner=AsyncMock())
    cog.shiny_seen = None
    cog.clip_task = None

    async def run():
        # A shiny already pending at startup isn't clipped
        cog.watch_shiny()
        assert cog.clip_task is None
        uns.nxbt_daemon_stop = False
        cog.watch_shiny()
        uns.nxbt_daemon_stop = True
        cog.watch_shiny()
        await cog.clip_task
        # Still stopped on the same shiny: no second clip
        cog.watch_shiny()
        assert cog.clip_task.done()

    asyncio.run(run())

    assert clips == ["Shiny Cresselia!"]
    text = cog.bot.messenger.msg_owner.await_args.args[0]
    assert text == "🎬 Clipped the shiny: https://twitch.tv/x/clip/c"


def test_needs_authorization_for_missing_scopes_or_a_dead_token(tmp_path):
    from cynthia.utils.twitchapi import TwitchAuthError

    api = TwitchAPI("client", None, Drive(tmp_path))
    assert asyncio.run(api.needs_authorization())

    api.tokens = {
        "access_token": "a",
        "refresh_token": "r",
        "expires_at": time.time() + 3600,
        "user_id": "42",
        "scopes": ["channel:manage:broadcast"],
    }
    assert asyncio.run(api.needs_authorization())

    api.tokens["scopes"].append("clips:edit")
    assert not asyncio.run(api.needs_authorization())

    async def dead(session, force=False):
        raise TwitchAuthError("expired")

    api._access_token = dead
    assert asyncio.run(api.needs_authorization())
