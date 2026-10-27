import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cynthia.bot.cogs.status import StatusCog
from cynthia.utils.drive import Drive
from cynthia.utils.encounters import encounter_log_name
from cynthia.utils.namespace import Namespace


def make_status_cog(tmp_path, *, hunt, self_encounter=False):
    log_name = encounter_log_name(hunt) if hunt else None
    if log_name:
        (tmp_path / log_name).write_text(
            "2026-10-27 12:00:00.000000, first\n" "2026-10-27 12:00:02.000000, second\n"
        )
    daemon = SimpleNamespace(
        ns=SimpleNamespace(
            game="Pokemon Brilliant Diamond",
            home=False,
            playing=True,
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
        drive=Drive(tmp_path),
        messenger=SimpleNamespace(msg_owner=AsyncMock()),
    )
    return StatusCog(bot), log_name


def test_status_hunt_uses_per_hunt_log_and_count(tmp_path):
    cog, log_name = make_status_cog(tmp_path, hunt="Uxie")

    bot_activity, user_activity = asyncio.run(cog.get_status())

    assert log_name == "encounter_times.uxie.log"
    assert bot_activity["count"].name == "2 encounters"
    assert user_activity["details"] == "Hunting shiny Uxie"
    assert user_activity["state"] == "2 encounters"
    assert isinstance(user_activity["timestamps"]["start"], int)
    assert (tmp_path / log_name).exists()
    assert not (tmp_path / "encounter_times.log").exists()


def test_status_self_encounter_uses_reset_count(tmp_path):
    cog, _ = make_status_cog(tmp_path, hunt="Uxie", self_encounter=True)

    bot_activity, user_activity = asyncio.run(cog.get_status())

    assert bot_activity["count"].name == "2 resets"
    assert user_activity["details"] == "Looking for shiny Uxie"
    assert user_activity["state"] == "2 resets"


def test_status_without_hunt_reports_game_only(tmp_path):
    cog, _ = make_status_cog(tmp_path, hunt=None)

    bot_activity, user_activity = asyncio.run(cog.get_status())

    assert bot_activity.name == "Pokemon Brilliant Diamond"
    assert user_activity["name"] == "Pokemon Brilliant Diamond"
    assert "details" not in user_activity
