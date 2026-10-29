import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cynthia.bot.applications.status import clear_status, set_status
from cynthia.bot.cogs.status import StatusCog, game_image_asset
from cynthia.utils.drive import Drive
from cynthia.utils.encounters import encounter_log_name
from cynthia.utils.namespace import Namespace


def make_vars(text=None, start=None):
    return Namespace({"status": Namespace({"text": text, "start": start})})


def make_status_cog(
    tmp_path, *, hunt, self_encounter=False, playing=True, home=False, vars=None
):
    log_name = encounter_log_name(hunt) if hunt else None
    if log_name:
        (tmp_path / log_name).write_text(
            "2026-10-27 12:00:00.000000, first\n" "2026-10-27 12:00:02.000000, second\n"
        )
    daemon = SimpleNamespace(
        ns=SimpleNamespace(
            game="Pokemon Brilliant Diamond",
            home=home,
            playing=playing,
            self_encounter=self_encounter,
            embed=None,
            png=None,
        )
    )
    bot = SimpleNamespace(
        dman=SimpleNamespace(
            running_daemons={"CVDaemon": daemon},
            uns=SimpleNamespace(
                nxbt_daemon_stop=False,
                nxbt_connection_lost=False,
            ),
        ),
        args=SimpleNamespace(hunt=hunt),
        vars=vars or make_vars(),
        drive=Drive(tmp_path),
        messenger=SimpleNamespace(msg_owner=AsyncMock()),
    )
    return StatusCog(bot), log_name


def test_status_hunt_uses_per_hunt_log_and_count(tmp_path):
    cog, log_name = make_status_cog(tmp_path, hunt="Uxie")

    bot_activity, user_activity = asyncio.run(cog.get_status())

    assert log_name == "encounter_times.uxie.log"
    assert bot_activity[2].name == "2 encounters"
    assert user_activity["details"] == "Hunting shiny Uxie"
    assert user_activity["state"] == "2 encounters"
    assert isinstance(user_activity["timestamps"]["start"], int)
    assert (tmp_path / log_name).exists()
    assert not (tmp_path / "encounter_times.log").exists()


def test_status_with_disabled_drive_keeps_hunt_status_without_file_io(tmp_path):
    cog, _ = make_status_cog(tmp_path, hunt="Uxie")
    cog.bot.drive = Drive(None)
    cog.bot.started_at_ms = 123

    asyncio.run(cog.update_status.coro(cog))

    assert cog.user_activity["details"] == "Hunting shiny Uxie"
    assert cog.user_activity["state"] == "No encounters yet"
    assert cog.get_activity_stats() == {"bot_started": 123}


def test_status_self_encounter_uses_reset_count(tmp_path):
    cog, _ = make_status_cog(tmp_path, hunt="Uxie", self_encounter=True)

    bot_activity, user_activity = asyncio.run(cog.get_status())

    assert bot_activity[2].name == "2 resets"
    assert user_activity["details"] == "Looking for shiny Uxie"
    assert user_activity["state"] == "2 resets"


def test_status_without_hunt_reports_game_only(tmp_path):
    cog, _ = make_status_cog(tmp_path, hunt=None)

    bot_activity, user_activity = asyncio.run(cog.get_status())

    assert bot_activity.name == "Pokemon Brilliant Diamond"
    assert user_activity["name"] == "Pokemon Brilliant Diamond"
    assert "details" not in user_activity


@pytest.mark.parametrize(
    "game,asset",
    [
        ("Pokémon HOME", "pokemon_home_logo"),
        ("Pokémon Legends: Arceus", "pokemon_legends_arceus_logo"),
        ("Pokémon Legends: Z-A", "pokemon_legends_za_logo"),
        ("Pokémon Scarlet", "pokemon_scarlet_logo"),
        ("Pokémon Violet", "pokemon_violet_logo"),
        ("Pokémon Sword", "pokemon_sword_logo"),
        ("Pokémon Shield", "pokemon_shield_logo"),
        ("Pokémon Brilliant Diamond", "dialga_glow"),
        ("Pokémon Shining Pearl", "palkia_glow"),
        ("Unknown Game", "nintendo_switch"),
    ],
)
def test_game_image_asset(game, asset):
    assert game_image_asset(game) == asset


@pytest.mark.parametrize(
    "game,asset",
    [
        ("Pokémon HOME", "pokemon_home_logo"),
        ("Pokémon Legends: Arceus", "pokemon_legends_arceus_logo"),
        ("Pokémon Legends: Z-A", "pokemon_legends_za_logo"),
        ("Pokémon Scarlet", "pokemon_scarlet_logo"),
        ("Pokémon Shield", "pokemon_shield_logo"),
    ],
)
def test_hunt_activity_includes_matching_game_asset(game, asset, tmp_path):
    cog, _ = make_status_cog(tmp_path, hunt="Darkrai")
    cog.bot.dman.running_daemons["CVDaemon"].ns.game = game

    _, user_activity = asyncio.run(cog.get_status())

    assert user_activity["details"] == "Hunting shiny Darkrai"
    assert user_activity["assets"]["large_image"] == asset


def test_status_custom_text_added_to_game_activity(tmp_path):
    start = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
    cog, _ = make_status_cog(tmp_path, hunt=None, vars=make_vars("Resetting", start))

    bot_activity, user_activity = asyncio.run(cog.get_status())

    assert bot_activity[0].name == "Pokemon Brilliant Diamond"
    assert bot_activity[1].name == "Resetting"
    assert user_activity["details"] == "Resetting"
    assert user_activity["timestamps"] == {"start": int(start.timestamp() * 1000)}
    json.dumps(user_activity)


def test_status_custom_text_without_time_has_no_timestamps(tmp_path):
    cog, _ = make_status_cog(tmp_path, hunt=None, vars=make_vars("Resetting"))

    _, user_activity = asyncio.run(cog.get_status())

    assert "timestamps" not in user_activity


def test_status_hunt_takes_precedence_over_custom_text(tmp_path):
    cog, _ = make_status_cog(tmp_path, hunt="Uxie", vars=make_vars("Custom"))

    _, user_activity = asyncio.run(cog.get_status())

    assert user_activity["details"] == "Hunting shiny Uxie"


def test_status_custom_text_when_not_playing(tmp_path):
    cog, _ = make_status_cog(
        tmp_path, hunt=None, playing=False, vars=make_vars("Be right back")
    )

    bot_activity, user_activity = asyncio.run(cog.get_status())

    assert bot_activity.name == "Be right back"
    assert user_activity is None


def test_status_no_activity_when_idle_without_text(tmp_path):
    cog, _ = make_status_cog(tmp_path, hunt=None, playing=False)

    assert asyncio.run(cog.get_status()) == (None, None)


def _interaction(vars):
    return SimpleNamespace(
        client=SimpleNamespace(vars=vars),
        response=SimpleNamespace(send_message=AsyncMock()),
    )


def test_set_status_command_updates_vars():
    vars = make_vars()
    interaction = _interaction(vars)

    asyncio.run(set_status.callback(interaction, "Shiny hunting"))

    assert vars.status.text == "Shiny hunting"
    assert vars.status.start is not None
    interaction.response.send_message.assert_awaited_once()


def test_set_status_command_without_time():
    vars = make_vars(start=datetime.now(timezone.utc))
    interaction = _interaction(vars)

    asyncio.run(set_status.callback(interaction, "Shiny hunting", False))

    assert vars.status.text == "Shiny hunting"
    assert vars.status.start is None


def test_clear_status_command_resets_vars():
    vars = make_vars("Shiny hunting", datetime.now(timezone.utc))
    interaction = _interaction(vars)

    asyncio.run(clear_status.callback(interaction))

    assert vars.status.text is None
    assert vars.status.start is None
    interaction.response.send_message.assert_awaited_once()
