import asyncio
import gzip
import importlib
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import yaml

from cynthia.bot.applications.tree import CommandTree
from cynthia.context.perms import PermsLoader, guild_key
from cynthia.daemons.cystream import GzipLogHandler
from cynthia.daemons.nxbt import NXBTDaemon
from cynthia.utils.drive import Drive
from cynthia.utils.encounters import (
    DEFAULT_ENCOUNTER_LOG,
    average_interval_ms,
    encounter_log_name,
    parse_encounter_log,
)
from cynthia.utils.namespace import Namespace
from cynthia.utils.snowflake import GuildFlake, PermFlake, Snowflake
from cynthia.utils.types import force_obj_is_dict, force_obj_is_list


def test_snowflakes_compare_and_hash_by_value():
    first = GuildFlake("123")
    second = GuildFlake("g:123")

    assert first == second
    assert {first: "guild"}[second] == "guild"
    assert first == Snowflake(euid="g:123")
    assert str(PermFlake(flake_type="user", uid="456", allow=False)) == "-u:456"


def test_namespace_and_type_conversions():
    namespace = Namespace({"guild id": 123})

    assert namespace.guild_id == 123
    assert namespace.get("missing", None) is None
    assert force_obj_is_list({"a": 1}) == [("a", 1)]
    assert force_obj_is_dict(["a", "b"]) == {0: "a", 1: "b"}


def test_drive_checks_and_gzip_io(tmp_path):
    drive = Drive(tmp_path)
    target = tmp_path / "test.gz"

    with drive.gopen("test.gz", "wt") as stream:
        stream.write("record")

    assert drive.exists("test.gz", is_file=True)
    with gzip.open(target, "rt") as stream:
        assert stream.read() == "record"
    assert Drive(None).path("missing") is None


def test_average_interval_ms_drops_outliers():
    stamps = ("00:00:00", "00:00:01", "00:00:03", "00:00:04", "01:00:00")
    lines = [f"2026-01-01 {t}.0,Game,500\n" for t in stamps]
    assert average_interval_ms(lines) == 1333.3333333333333
    assert average_interval_ms(lines[:1]) is None
    assert average_interval_ms([]) is None


def test_watchdog_timeout_never_drops_below_default(tmp_path):
    drive = Drive(tmp_path)
    stamps = [f"00:00:{i:02d}" for i in range(20)]
    with drive.open("fast.csv", "w") as f:
        f.writelines(f"2026-01-01 {t}.0,Game,500\n" for t in stamps)
    assert NXBTDaemon.watchdog_timeout(drive, "fast.csv") == 900.0


def test_stop_start_markers_are_excluded_from_hunt_time():
    lines = [
        "2026-01-01 00:00:00.0,Game,500\n",
        "2026-01-01 00:00:02.0,Game,500\n",
        "2026-01-01 00:00:03.0,#STOP,paused\n",
        "2026-01-01 01:00:03.0,#START,\n",
        "2026-01-01 01:00:05.0,Game,500\n",
        "2026-01-01 01:00:06.0,#STOP,shutdown\n",
    ]
    log = parse_encounter_log(lines)
    assert len(log.encounters) == 3
    assert log.paused_ms == 3_600_000
    assert log.stopped_at is not None
    assert average_interval_ms(lines) == 2500


def test_start_without_stop_counts_gap_as_pause():
    lines = [
        "2026-01-01 00:00:00.0,Game,500\n",
        "2026-01-01 00:10:00.0,#START,\n",
    ]
    assert parse_encounter_log(lines).paused_ms == 600_000


def test_encounter_log_name_is_stable():
    assert encounter_log_name("Ho-Oh") == "encounter_times.hooh.log"
    assert encounter_log_name("!!!") == DEFAULT_ENCOUNTER_LOG
    assert encounter_log_name(None) == DEFAULT_ENCOUNTER_LOG


def test_permissions_load_dedupes_owner_and_scopes_guilds(tmp_path):
    path = tmp_path / "perms.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "global": {
                    "privileged": ["+u:10", "+u:10"],
                    "allowed_commands": ["status"],
                },
                "g:20": {"admins": ["+r:30"]},
            }
        )
    )
    bot = SimpleNamespace(owner="10", guilds=[SimpleNamespace(id=20)])
    loader = PermsLoader(path)
    perms = loader(bot)
    loader._perms = perms

    assert perms["global"]["privileged"] == ["+u:10"]
    assert perms[guild_key(20)]["admins"] == ["+r:30", "+u:10"]
    assert loader.ensure_guild(21)[0] == "g:21"
    assert perms["g:21"]["admins"] == ["+u:10"]


def test_permissions_grant_deny_revoke_and_command_allowlist(tmp_path):
    path = tmp_path / "perms.yaml"
    path.write_text("{}")
    bot = SimpleNamespace(owner="1", guilds=[])
    loader = PermsLoader(path)
    loader._perms = loader(bot)

    assert loader.grant("global", "drive", "u", 22) == "added"
    assert loader.grant("global", "drive", "u", 22, allow=False) == "updated"
    assert "-u:22" in loader._perms["global"]["drive"]
    assert loader.revoke("global", "drive", "u", 22)
    assert not loader.revoke("global", "drive", "u", 22)
    assert loader.allow_command("global", "status")
    assert not loader.allow_command("global", "status")
    assert loader.disallow_command("global", "status")
    assert not loader.disallow_command("global", "status")


def test_permission_check_does_not_mutate_context_lists(tmp_path):
    path = tmp_path / "perms.yaml"
    path.write_text("{}")
    bot = SimpleNamespace(owner="1", guilds=[SimpleNamespace(id=20)])
    loader = PermsLoader(path)
    loader._perms = loader(bot)
    loader._perms["global"]["privileged"].append("+r:30")
    before = list(loader._perms["global"]["privileged"])
    context = SimpleNamespace(
        user=SimpleNamespace(id=40, roles=[SimpleNamespace(id=30)]),
        guild_id=20,
    )

    assert loader.check(context, perm="privileged")
    assert loader._perms["global"]["privileged"] == before


def test_gzip_access_handler_writes_readable_records(tmp_path):
    path = tmp_path / "access.log.gz"
    handler = GzipLogHandler(path)
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 0, 'GET / HTTP/1.1" 200', (), None
    )

    handler.emit(record)
    handler.close()

    with gzip.open(path, "rt") as stream:
        assert 'GET / HTTP/1.1" 200' in stream.read()


def test_tree_reloads_one_application_and_preserves_old_commands(monkeypatch):
    async def run():
        client = discord.Client(intents=discord.Intents.none())
        tree = CommandTree(client)
        tree._CommandTree__modules = ["auth"]
        tree.clear_commands()

        assert await tree._load_module("auth") is None
        previous = list(tree.get_commands())
        assert previous
        assert await tree.reload_module("auth") == []
        assert [command.name for command in tree.get_commands()] == [
            command.name for command in previous
        ]
        assert await tree.reload_module("missing") == [
            "Unknown application module: missing"
        ]

        original_reload = importlib.reload

        def fail_auth(module):
            if module.__name__ == "cynthia.bot.applications.auth":
                raise SyntaxError("broken module")
            return original_reload(module)

        monkeypatch.setattr("cynthia.bot.applications.tree.importlib.reload", fail_auth)
        errors = await tree.reload_module("auth")
        assert "broken module" in errors[0]
        assert [command.name for command in tree.get_commands()] == [
            command.name for command in previous
        ]
        await client.close()

    asyncio.run(run())


def test_tree_check_failure_responds_ephemerally():
    async def run():
        client = discord.Client(intents=discord.Intents.none())
        tree = CommandTree(client)
        response = SimpleNamespace(
            is_done=Mock(return_value=False), send_message=AsyncMock()
        )
        interaction = SimpleNamespace(response=response)

        await tree.on_error(interaction, discord.app_commands.CheckFailure("denied"))

        response.send_message.assert_awaited_once_with("❌ denied", ephemeral=True)
        await client.close()

    asyncio.run(run())


def test_all_source_files_compile():
    root = Path(__file__).parents[1] / "cynthia"
    for path in root.rglob("*.py"):
        compile(path.read_text(), str(path), "exec")


def test_every_application_module_and_command_is_registered():
    async def run():
        client = discord.Client(intents=discord.Intents.none())
        tree = CommandTree(client)

        count, errors = await tree.load_commands()

        commands = tree.get_commands()
        names = [command.name for command in commands]
        assert not errors
        assert set(tree.loaded_modules) == set(tree.modules)
        assert count == len(commands)
        assert len(names) == len(set(names))
        leaves = [
            leaf
            for command in commands
            for leaf in (
                command.walk_commands()
                if isinstance(command, discord.app_commands.Group)
                else [command]
            )
            if not isinstance(leaf, discord.app_commands.Group)
        ]
        assert all(callable(leaf.callback) for leaf in leaves)
        assert all(
            callable(check) for leaf in leaves for check in getattr(leaf, "checks", [])
        )
        await client.close()

    asyncio.run(run())


def test_ternary_waits_out_stale_cv_data(monkeypatch):
    import asyncio
    import time
    from types import SimpleNamespace

    from cynthia.utils.nxbt_utils import Ternary

    monkeypatch.setattr(Ternary, "CV_WAIT_TIMEOUT", 0.5)
    uns = SimpleNamespace(cv_frame_time=time.time() - 60, scene_matched=False)
    try:
        asyncio.run(Ternary("a", "b", "c")._evaluate(uns=uns))
    except TimeoutError:
        pass
    else:
        raise AssertionError("stale CV data must not yield a false result")

    uns.cv_frame_time = time.time() + 100
    assert asyncio.run(Ternary("a", "b", "c")._evaluate(uns=uns)) is False
