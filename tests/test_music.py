import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest
import yaml
from discord import app_commands

from cynthia.bot.applications import music as music_app
from cynthia.bot.applications.tree import CommandTree
from cynthia.context.perms import PermsLoader
from cynthia.utils import music
from cynthia.utils.music import GuildPlayer, MusicError, Track, best_match, find_track


def entry(title, **extra):
    return {"title": title, "id": title.replace(" ", "_"), **extra}


def test_best_match_prefers_closest_title_and_skips_live_streams():
    results = [
        entry("Totally unrelated mix", live_status="not_live"),
        entry("Daft Punk - Get Lucky (live radio)", is_live=True),
        entry("Daft Punk - Get Lucky (Official Audio)"),
    ]

    assert best_match("daft punk get lucky", results)["title"].endswith(
        "(Official Audio)"
    )
    assert best_match("anything", [entry("x", is_live=True)]) is None


def test_best_match_uses_search_rank_to_break_ties():
    results = [entry("Same Song"), entry("Same Song")]

    assert best_match("same song", results) is results[0]


def test_find_track_searches_youtube_for_text_and_loads_links_directly(monkeypatch):
    calls = []

    def fake_extract(target, flat=False):
        calls.append((target, flat))
        if target.startswith("https://music.youtube.com"):
            return {"entries": []}
        if target.startswith("ytsearch"):
            return {"entries": [entry("Never Gonna Give You Up", duration=213)]}
        return {"title": "Direct", "webpage_url": target, "duration": 5}

    monkeypatch.setattr(music, "_extract", fake_extract)

    async def run():
        searched = await find_track("never gonna give you up", "ann")
        linked = await find_track("https://youtu.be/abc", "ann")
        return searched, linked

    searched, linked = asyncio.run(run())

    assert (f"ytsearch{music.SEARCH_RESULTS}:never gonna give you up", True) in calls
    assert ("https://youtu.be/abc", False) in calls
    assert searched.url == "https://www.youtube.com/watch?v=Never_Gonna_Give_You_Up"
    assert (linked.title, linked.url, linked.requester) == (
        "Direct",
        "https://youtu.be/abc",
        "ann",
    )


def test_find_track_reports_no_results(monkeypatch):
    monkeypatch.setattr(music, "_extract", lambda *a, **k: {"entries": []})

    with pytest.raises(MusicError, match="No playable results"):
        asyncio.run(find_track("zzzz", "ann"))


class FakeVoice:
    def __init__(self):
        self.playing = None
        self.after = None
        self.paused = False

    def is_connected(self):
        return True

    def is_playing(self):
        return self.playing is not None and not self.paused

    def is_paused(self):
        return self.playing is not None and self.paused

    def play(self, source, after):
        self.playing, self.after = source, after

    def stop(self):
        after, self.playing, self.paused = self.after, None, False
        if after:
            after(None)

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False


def make_player(monkeypatch, failing=()):
    voice = FakeVoice()
    guild = SimpleNamespace(voice_client=voice)
    monkeypatch.setattr(
        music,
        "_extract_stream",
        lambda url: (
            (_ for _ in ()).throw(RuntimeError()) if url in failing else f"stream:{url}"
        ),
    )
    monkeypatch.setattr(
        music.discord, "FFmpegPCMAudio", lambda stream, **kwargs: stream
    )
    return GuildPlayer(guild), voice


def song(name):
    return Track(title=name, url=f"https://x/{name}", duration=60, requester="ann")


async def settle():
    # Stream URLs resolve in a worker thread, so let it finish
    await asyncio.sleep(0.05)


def test_player_plays_first_track_and_queues_the_rest_in_order(monkeypatch):
    async def run():
        player, voice = make_player(monkeypatch)
        positions = [player.add(song(n)) for n in "abc"]
        await settle()
        assert positions == [0, 1, 2]
        assert (player.current.title, voice.playing) == ("a", "stream:https://x/a")

        assert player.skip().title == "a"
        await settle()
        assert (player.current.title, [t.title for t in player.queue]) == ("b", ["c"])

        voice.stop()  # natural end of "b"
        await settle()
        assert player.current.title == "c"

        voice.stop()
        await settle()
        assert (player.current, voice.playing, len(player.queue)) == (None, None, 0)

    asyncio.run(run())


def test_player_pause_resume_clear_and_stop(monkeypatch):
    async def run():
        player, voice = make_player(monkeypatch)
        for n in "abc":
            player.add(song(n))
        await settle()

        assert player.pause() and player.paused
        assert not player.pause()
        assert player.resume() and not player.paused

        assert player.clear() == 2
        assert player.current.title == "a"

        player.add(song("d"))
        player.stop()
        await settle()
        assert (player.current, voice.playing, len(player.queue)) == (None, None, 0)

    asyncio.run(run())


def test_player_skips_tracks_that_fail_to_start(monkeypatch):
    async def run():
        player, voice = make_player(monkeypatch, failing={"https://x/a"})
        player.add(song("a"))
        player.add(song("b"))
        await settle()

        assert player.current.title == "b"
        assert voice.playing == "stream:https://x/b"

    asyncio.run(run())


def test_player_refuses_a_full_queue(monkeypatch):
    async def run():
        player, _ = make_player(monkeypatch)
        for n in range(music.MAX_QUEUE + 1):
            player.add(song(str(n)))
        with pytest.raises(MusicError, match="full"):
            player.add(song("extra"))

    asyncio.run(run())


def test_music_commands_exist_and_are_guild_only():
    names = {command.name for command in music_app.music.walk_commands()}

    assert names == {
        "play",
        "pause",
        "skip",
        "stop",
        "queue",
        "clear",
        "search",
        "join",
        "leave",
        "pin",
        "unpin",
        "pins",
    }
    assert music_app.music.guild_only


def test_music_group_is_nonglobal_by_default(tmp_path):
    perms_file = tmp_path / "perms.yaml"
    perms_file.write_text("{}")
    loader = PermsLoader(perms_file)
    loader._perms = loader(SimpleNamespace(owner="10", guilds=[SimpleNamespace(id=20)]))
    interaction = SimpleNamespace(
        guild=SimpleNamespace(id=20),
        guild_id=20,
        user=SimpleNamespace(id=10, roles=[]),
        client=SimpleNamespace(perms_check=loader.check),
    )

    async def run():
        with pytest.raises(app_commands.CheckFailure, match="not allowed"):
            await music_app.music.interaction_check(interaction)
        loader.allow_command("g:20", "music")
        assert await music_app.music.interaction_check(interaction)

    asyncio.run(run())


def test_music_application_loads_into_the_command_tree():
    async def run():
        tree = CommandTree(discord.Client(intents=discord.Intents.none()))
        tree.clear_commands()
        error = await tree._load_module("music")
        return error, tree.get_command("music")

    error, command = asyncio.run(run())

    assert error is None
    assert command is not None


def result(title, channel, views, duration, vid, **extra):
    return {
        "title": title,
        "channel": channel,
        "view_count": views,
        "duration": duration,
        "id": vid,
        **extra,
    }


def test_best_match_prefers_original_song_over_popular_mixes_and_covers():
    results = [
        result("Get Lucky 10 hours", "loops", 90_000_000, 36000, "a" * 11),
        result("Get Lucky (cover)", "someone", 50_000_000, 240, "b" * 11),
        result("Get Lucky snippet", "clips", 80_000_000, 20, "c" * 11),
        result(
            "Daft Punk - Get Lucky (Official Audio)",
            "Daft Punk",
            9_000_000,
            249,
            "d" * 11,
        ),
    ]

    assert best_match("get lucky", results)["id"] == "d" * 11


def test_best_match_uses_youtube_music_membership_and_views():
    reupload = result("Song Name", "random uploader", 1_000, 200, "a" * 11)
    original = result("Song Name", "Some Artist - Topic", 5_000_000, 200, "b" * 11)

    assert best_match("song name", [reupload, original])["id"] == "b" * 11
    assert best_match("song name", [original, reupload])["id"] == "b" * 11
    assert best_match("song name", [reupload, original], {"b" * 11: 0})["id"] == (
        "b" * 11
    )


def test_off_version_words_are_allowed_when_the_query_asks_for_them():
    live = result("Band - Song (Live)", "Band", 1_000_000, 240, "a" * 11)
    studio = result("Band - Song", "Band", 1_000_000, 240, "b" * 11)

    assert best_match("band song", [live, studio])["id"] == "b" * 11
    assert best_match("band song live", [studio, live])["id"] == "a" * 11


def test_pins_match_similar_queries_and_persist(tmp_path):
    from cynthia.utils.drive import Drive

    drive = Drive(tmp_path)
    store = music.PinStore(drive)
    pin = music.Pin(
        "Band - Song (Official Audio)", "https://x/song", 200, "song", "ann"
    )
    assert store.add(1, pin) is False
    assert store.add(1, pin) is True

    assert store.match(1, "band song") is pin
    assert store.match(1, "something else entirely") is None
    assert store.match(2, "song") is None
    assert store.match(1, "song cover") is None

    reloaded = music.PinStore(drive)
    assert [p.url for p in reloaded.list(1)] == ["https://x/song"]
    assert reloaded.remove(1, 2) is None
    assert reloaded.remove(1, 1).url == "https://x/song"
    assert music.PinStore(drive).list(1) == []


def test_find_track_returns_the_pinned_song_without_searching(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("search should be skipped")

    monkeypatch.setattr(music, "_extract", no_network)
    pin = music.Pin("Pinned Song", "https://x/p", 100, "pinned", "ann")

    track = asyncio.run(find_track("pinned", "bob", pin))

    assert (track.url, track.pinned, track.requester) == ("https://x/p", True, "bob")


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.youtube.com/playlist?list=PLabc", True),
        ("https://music.youtube.com/playlist?list=OLAK5uy_abc", True),
        ("https://music.youtube.com/watch?v=4D7u5KF7SP8&list=PLabc", False),
        ("https://www.youtube.com/watch?v=4D7u5KF7SP8", False),
        ("https://www.youtube.com/watch?list=RDabc", False),
    ],
)
def test_is_playlist_url(url, expected):
    assert music.is_playlist_url(url) is expected


def test_load_playlist_skips_unavailable_and_caps_length(monkeypatch):
    entries = [{"title": "[Private video]", "id": "p" * 11}, None]
    entries += [
        {"title": f"Song {n}", "id": f"{n:011d}", "duration": 100}
        for n in range(music.MAX_PLAYLIST + 5)
    ]
    monkeypatch.setattr(
        music, "_extract", lambda *a, **k: {"title": "Mix", "entries": entries}
    )

    name, tracks = asyncio.run(
        music.load_playlist("https://x/playlist?list=PL1", "ann")
    )

    assert name == "Mix"
    assert len(tracks) == music.MAX_PLAYLIST
    assert tracks[0].title == "Song 0"


def test_load_playlist_without_songs_errors(monkeypatch):
    monkeypatch.setattr(music, "_extract", lambda *a, **k: {"entries": []})

    with pytest.raises(MusicError, match="no playable songs"):
        asyncio.run(music.load_playlist("https://x/playlist?list=PL1", "ann"))
