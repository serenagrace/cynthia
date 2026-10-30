import asyncio
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from cynthia.bot.applications.tree import CommandTree
from cynthia.bot.bot import Bot
from cynthia.daemons import dman as dman_module
from cynthia.daemons.dman import DMan
from cynthia.utils.namespace import Namespace


def test_command_tree_loads_all_application_modules():
    async def run():
        client = discord.Client(intents=discord.Intents.none())
        tree = CommandTree(client)

        count, errors = await tree.load_commands()

        assert errors == []
        assert count > 0
        assert set(tree.loaded_modules) == set(tree.modules)
        assert len(tree.loaded_commands) == count
        await client.close()

    asyncio.run(run())


def test_test_mode_requires_a_guild_scope():
    with pytest.raises(ValueError, match="requires an explicit test guild ID"):
        Bot(SimpleNamespace(), test_mode=True)


def test_test_mode_syncs_only_the_designated_guild():
    tree = SimpleNamespace(
        copy_global_to=Mock(),
        sync=AsyncMock(return_value=[]),
    )
    bot = SimpleNamespace(
        test_mode=True,
        command_guild_id=123,
        tree=tree,
    )

    asyncio.run(Bot._sync_command_tree(bot))

    tree.copy_global_to.assert_called_once()
    tree.copy_global_to.assert_called_once_with(guild=discord.Object(id=123))
    tree.sync.assert_awaited_once_with(guild=discord.Object(id=123))


def test_daemon_reload_replaces_class_and_restarts_one_daemon(monkeypatch):
    class OldDaemon:
        pass

    class NewDaemon:
        pass

    module = ModuleType("test_reload_daemon_module")
    module.CYStream = NewDaemon
    monkeypatch.setitem(sys.modules, OldDaemon.__module__, sys.modules[__name__])
    monkeypatch.setattr(dman_module.importlib, "reload", Mock(return_value=module))

    manager = object.__new__(DMan)
    manager._DMan__loaded_daemons = Namespace({"CYStream": OldDaemon})
    manager._DMan__running_daemons = Namespace({"CYStream": object()})
    manager.stop_daemons = AsyncMock()

    async def stop_one(*, daemons):
        manager._DMan__running_daemons.__delitem__(daemons[0])

    manager.stop_daemons.side_effect = stop_one
    manager.run_daemons = Mock()

    asyncio.run(DMan.reload_daemon(manager, "CYStream"))

    assert manager.loaded_daemons["CYStream"] is NewDaemon
    manager.stop_daemons.assert_awaited_once_with(daemons=["CYStream"])
    manager.run_daemons.assert_called_once_with(daemons=["CYStream"])


def test_daemon_reload_rejects_unsupported_name_without_side_effects():
    manager = object.__new__(DMan)
    manager._DMan__loaded_daemons = Namespace()
    manager._DMan__running_daemons = Namespace()
    manager.stop_daemons = AsyncMock()
    manager.run_daemons = Mock()

    with pytest.raises(ValueError, match="not reloadable"):
        asyncio.run(DMan.reload_daemon(manager, "NXBTDaemon"))

    manager.stop_daemons.assert_not_awaited()
    manager.run_daemons.assert_not_called()


def test_daemon_reload_import_failure_keeps_current_daemon_running(monkeypatch):
    class CurrentDaemon:
        pass

    monkeypatch.setitem(sys.modules, CurrentDaemon.__module__, sys.modules[__name__])
    monkeypatch.setattr(
        dman_module.importlib,
        "reload",
        Mock(side_effect=SyntaxError("invalid daemon source")),
    )
    manager = object.__new__(DMan)
    manager._DMan__loaded_daemons = Namespace({"CYStream": CurrentDaemon})
    manager._DMan__running_daemons = Namespace({"CYStream": object()})
    manager.stop_daemons = AsyncMock()
    manager.run_daemons = Mock()

    with pytest.raises(SyntaxError, match="invalid daemon source"):
        asyncio.run(DMan.reload_daemon(manager, "CYStream"))

    assert "CYStream" in manager.running_daemons
    manager.stop_daemons.assert_not_awaited()
    manager.run_daemons.assert_not_called()


def test_cog_reload_rejects_unknown_extension_without_loading():
    bot = SimpleNamespace(
        discovered_cogs=[],
        _discover_cogs=Mock(return_value=[]),
        load_extension=AsyncMock(),
        reload_extension=AsyncMock(),
        extensions={},
    )

    result = asyncio.run(Bot.reload_cog(bot, "cynthia.bot.cogs.missing"))

    assert result == "Unknown cog: cynthia.bot.cogs.missing"
    bot.load_extension.assert_not_awaited()
    bot.reload_extension.assert_not_awaited()
