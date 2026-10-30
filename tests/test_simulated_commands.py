import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest
import yaml
from discord import app_commands

from cynthia.bot.applications import apps as apps_app
from cynthia.bot.applications import auth as auth_app
from cynthia.bot.applications import cogs as cogs_app
from cynthia.bot.applications import config as config_app
from cynthia.bot.applications import control
from cynthia.bot.applications import nxbt as nxbt_app
from cynthia.context.perms import PermsLoader
from cynthia.utils.namespace import Namespace


def make_interaction(tmp_path, *, user_id=10, guild_id=20):
    perms_file = tmp_path / "perms.yaml"
    perms_file.write_text("{}")
    loader = PermsLoader(perms_file)
    bot = SimpleNamespace(owner="10", guilds=[SimpleNamespace(id=guild_id)])
    permissions = loader(bot)
    loader._perms = permissions
    tree = SimpleNamespace(get_command=lambda name: SimpleNamespace(name=name))
    client = SimpleNamespace(
        owner="10",
        permsloader=loader,
        perms=Namespace(permissions),
        perms_check=loader.check,
        tree=tree,
    )
    user = SimpleNamespace(id=user_id, roles=[])
    response = SimpleNamespace(send_message=AsyncMock())
    return (
        SimpleNamespace(
            client=client,
            user=user,
            guild_id=guild_id,
            guild=SimpleNamespace(name="Test Guild", id=guild_id),
            response=response,
        ),
        perms_file,
    )


def test_simulated_command_allow_disallow_and_persistence(tmp_path):
    async def run():
        interaction, perms_file = make_interaction(tmp_path)

        await auth_app.command_allow.callback(interaction, "/status")
        interaction.response.send_message.assert_awaited_once()
        assert "now allowed" in interaction.response.send_message.await_args.args[0]
        assert (
            "status"
            in yaml.safe_load(perms_file.read_text())["g:20"]["allowed_commands"]
        )

        interaction.response.send_message.reset_mock()
        await auth_app.command_disallow.callback(interaction, "status")
        assert (
            "no longer allowed" in interaction.response.send_message.await_args.args[0]
        )
        assert (
            "status"
            not in yaml.safe_load(perms_file.read_text())["g:20"]["allowed_commands"]
        )

    asyncio.run(run())


def test_simulated_command_denies_non_owner_allowlist_edit(tmp_path):
    async def run():
        interaction, perms_file = make_interaction(tmp_path, user_id=99)

        await auth_app.command_allow.callback(interaction, "status")

        message = interaction.response.send_message.await_args.args[0]
        assert "global `owners`" in message
        assert "g:20" not in yaml.safe_load(perms_file.read_text())

    asyncio.run(run())


def test_simulated_grant_deny_revoke_and_permission_view(tmp_path):
    async def run():
        interaction, perms_file = make_interaction(tmp_path)
        target = SimpleNamespace(id=42)

        await auth_app.perms_grant.callback(
            interaction,
            app_commands.Choice(name="privileged", value="privileged"),
            target,
            deny=True,
        )
        assert "-u:42" in interaction.client.perms["g:20"]["privileged"]
        assert "Denied" in interaction.response.send_message.await_args.args[0]

        interaction.response.send_message.reset_mock()
        await auth_app.perms_revoke.callback(
            interaction,
            app_commands.Choice(name="privileged", value="privileged"),
            target,
        )
        assert "-u:42" not in interaction.client.perms["g:20"]["privileged"]
        assert "Removed" in interaction.response.send_message.await_args.args[0]

        interaction.response.send_message.reset_mock()
        await auth_app.perms_view.callback(interaction)
        embed = interaction.response.send_message.await_args.kwargs["embed"]
        assert embed.title == "Permissions for Test Guild"
        assert any(field.name == "allowed commands" for field in embed.fields)
        assert yaml.safe_load(perms_file.read_text())["g:20"]["privileged"]

    asyncio.run(run())


def test_simulated_autocomplete_filters_registered_and_allowed_commands(tmp_path):
    async def run():
        interaction, _ = make_interaction(tmp_path)
        interaction.client.tree.get_commands = lambda: [
            SimpleNamespace(name="status"),
            SimpleNamespace(name="shutdown"),
        ]
        interaction.namespace = SimpleNamespace(scope=None)

        options = await auth_app.allow_autocomplete(interaction, "stat")
        assert [option.value for option in options] == ["status"]

        auth_app.resolve_context(interaction, "guild")
        interaction.client.perms["g:20"]["allowed_commands"].append("status")
        options = await auth_app.allow_autocomplete(interaction, "")
        assert [option.value for option in options] == ["shutdown"]
        options = await auth_app.disallow_autocomplete(interaction, "")
        assert [option.value for option in options] == ["status"]

    asyncio.run(run())


def test_simulated_guild_check_enforces_allowlist(tmp_path):
    interaction, _ = make_interaction(tmp_path)
    interaction.command = SimpleNamespace(name="status")
    interaction.client.permsloader.allow_command("g:20", "status")
    from cynthia.utils.auth import nonglobal_command

    @nonglobal_command()
    async def checked_command():
        return None

    check = checked_command.__discord_app_commands_checks__[0]
    assert asyncio.run(check(interaction))

    interaction.client.permsloader.disallow_command("g:20", "status")
    with pytest.raises(app_commands.CheckFailure, match="not allowed"):
        asyncio.run(check(interaction))


def test_simulated_config_get_and_set_commands():
    async def run():
        config = Namespace({"silent": False})
        interaction = SimpleNamespace(
            client=SimpleNamespace(config=config),
            response=SimpleNamespace(send_message=AsyncMock()),
        )

        await config_app.cget.callback(interaction, "silent")
        interaction.response.send_message.assert_awaited_once_with(False)

        interaction.response.send_message.reset_mock()
        await config_app.cset.callback(interaction, "silent", "true")
        assert config.silent == "true"
        interaction.response.send_message.assert_awaited_once_with("Config updated.")

        interaction.response.send_message.reset_mock()
        await config_app.cset.callback(interaction, "unknown", "value")
        assert "not found" in interaction.response.send_message.await_args.args[0]
        assert "unknown" not in config

    asyncio.run(run())


def test_reload_autocomplete_lists_discovered_apps_and_cogs():
    async def run():
        interaction = SimpleNamespace(
            client=SimpleNamespace(
                tree=SimpleNamespace(modules=["auth", "control", "web"]),
                discovered_cogs=[
                    "cynthia.bot.cogs.bouncer",
                    "cynthia.bot.cogs.status",
                ],
            )
        )

        modules = await apps_app.application_autocomplete(interaction, "au")
        cogs = await cogs_app.cog_autocomplete(interaction, "status")

        assert [option.value for option in modules] == ["auth"]
        assert [option.name for option in cogs] == ["status"]
        assert cogs[0].value == "cynthia.bot.cogs.status"

    asyncio.run(run())


def test_nxbt_macro_autocomplete_is_bounded_and_case_insensitive(monkeypatch):
    async def run():
        from cynthia.utils.nxbt_utils import Macro

        old_tree = Macro._macro_tree
        Macro._macro_tree = {"zoom": "A", "cleanup": "B", "uxie": "X"}
        try:
            choices = await nxbt_app.macro_autocomplete(SimpleNamespace(), "O")
        finally:
            Macro._macro_tree = old_tree

        assert [choice.value for choice in choices] == ["zoom"]

    asyncio.run(run())


def test_simulated_forced_reboot_never_calls_host_command(monkeypatch):
    async def run():
        events = []

        async def send_message(message):
            events.append(("reply", message))

        async def sleep(_):
            events.append(("delay", None))

        async def subprocess(*args):
            events.append(("subprocess", args))

        monkeypatch.setattr(control.asyncio, "sleep", sleep)
        monkeypatch.setattr(control.asyncio, "create_subprocess_exec", subprocess)
        interaction = SimpleNamespace(
            response=SimpleNamespace(send_message=send_message)
        )

        await control.reboot.callback(interaction, graceful=False)

        assert [event[0] for event in events] == ["reply", "delay", "subprocess"]
        assert events[-1][1] == ("sudo", "-n", "reboot", "-f", "now")

    asyncio.run(run())


def test_simulated_switch_connect_and_disconnect_only_call_daemon():
    async def run():
        daemon = SimpleNamespace(
            connected=False,
            connect=AsyncMock(return_value=True),
            disconnect=AsyncMock(return_value=True),
        )
        interaction = SimpleNamespace(
            client=SimpleNamespace(
                dman=SimpleNamespace(running_daemons={"NXBTDaemon": daemon})
            ),
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await nxbt_app.connect.callback(interaction)
        daemon.connect.assert_awaited_once()
        assert "Connected" in interaction.followup.send.await_args.args[0]

        interaction.response.defer.reset_mock()
        interaction.followup.send.reset_mock()
        daemon.connected = True
        await nxbt_app.disconnect.callback(interaction)
        daemon.disconnect.assert_awaited_once()
        assert "Disconnected" in interaction.followup.send.await_args.args[0]

    asyncio.run(run())


def test_simulated_switch_and_queue_macro_only_queue_mocked_daemon():
    async def run():
        from cynthia.utils.nxbt_utils import Macro

        old_tree = Macro._macro_tree
        Macro._macro_tree = {"zoom": "A"}
        try:
            daemon = SimpleNamespace(
                connected=True,
                queue=Mock(),
                unpause=Mock(),
            )
            interaction = SimpleNamespace(
                client=SimpleNamespace(
                    dman=SimpleNamespace(running_daemons={"NXBTDaemon": daemon})
                ),
                response=SimpleNamespace(defer=AsyncMock()),
                followup=SimpleNamespace(send=AsyncMock()),
            )

            await nxbt_app.switch.callback(
                interaction,
                app_commands.Choice(name="A", value="A"),
            )
            daemon.queue.assert_called_once()
            daemon.unpause.assert_called_once()

            daemon.queue.reset_mock()
            interaction.followup.send.reset_mock()
            await nxbt_app.queue_macro.callback(interaction, "zoom")
            daemon.queue.assert_called_once_with("A")
            assert "Queued" in interaction.followup.send.await_args.args[0]
        finally:
            Macro._macro_tree = old_tree

    asyncio.run(run())
