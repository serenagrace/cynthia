import asyncio
import inspect
import os
import struct
import zlib
from pathlib import Path
from shlex import quote
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest
from discord import app_commands
from dotenv import dotenv_values

from cynthia.bot.applications import apps as apps_app
from cynthia.bot.applications import auth as auth_app
from cynthia.bot.applications import cogs as cogs_app
from cynthia.bot.applications import guild as guild_app
from cynthia.bot.applications import shell as shell_app
from cynthia.bot.bot import Bot
from cynthia.context.perms import PermsLoader
from cynthia.utils.namespace import Namespace
from cynthia.utils.onmessage import OnMessage
from cynthia.views import InsightView


def _png_fixture():
    def chunk(name, data):
        body = name.encode("ascii") + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    pixels = (b"\x00" + b"\x40\x80\xc0\xff" * 32) * 32
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk("IHDR", struct.pack(">2I5B", 32, 32, 8, 6, 0, 0, 0))
        + chunk("IDAT", zlib.compress(pixels))
        + chunk("IEND", b"")
    )


def _interaction(bot, guild, channel, member):
    return SimpleNamespace(
        client=bot,
        user=member,
        guild=guild,
        guild_id=guild.id,
        channel=channel,
        permissions=channel.permissions_for(member),
        response=SimpleNamespace(
            send_message=AsyncMock(),
            defer=AsyncMock(),
            send=AsyncMock(),
        ),
        followup=SimpleNamespace(
            send=AsyncMock(),
            send_message=AsyncMock(),
        ),
    )


async def _run_checks(command, interaction):
    interaction.command = command
    for check in command.checks:
        result = check(interaction)
        if inspect.isawaitable(result):
            await result


async def _probe_callback(interaction: discord.Interaction):
    return None


@pytest.mark.discord_live
def test_test_bot_exercises_live_guild_and_safe_command_callbacks(tmp_path):
    values = dotenv_values(Path(__file__).parents[1] / ".env.test")
    keys = (
        "DISCORD_TEST_BOT_TOKEN",
        "DISCORD_TEST_GUILD_ID",
        "DISCORD_TEST_CHANNEL_ID",
        "DISCORD_TEST_OWNER_ID",
        "DISCORD_TEST_ROLE_ID",
        "DISCORD_TEST_USER_ID",
    )
    config = {key: os.getenv(key) or values.get(key) for key in keys}
    missing = [key for key, value in config.items() if not value]
    if missing:
        pytest.skip(f"Set {', '.join(missing)} in .env.test.")

    guild_id = int(config["DISCORD_TEST_GUILD_ID"])
    bot_id_value = os.getenv("DISCORD_TEST_BOT_ID") or values.get("DISCORD_TEST_BOT_ID")
    bot_id = int(bot_id_value) if bot_id_value else None
    channel_id = int(config["DISCORD_TEST_CHANNEL_ID"])
    owner_id = int(config["DISCORD_TEST_OWNER_ID"])
    role_id = int(config["DISCORD_TEST_ROLE_ID"])
    user_id = int(config["DISCORD_TEST_USER_ID"])

    async def run():
        perms_file = tmp_path / "perms.yaml"
        perms_file.write_text("{}")
        (tmp_path / "site" / "html").mkdir(parents=True)
        context = SimpleNamespace(
            config=Namespace(
                {"drive_path": str(tmp_path), "owner": str(owner_id), "silent": True}
            ),
            app_meta=Namespace(
                {"run_timestamp": "test", "git_hash": "test", "git_timestamp": "test"}
            ),
            args=Namespace({"hunt": None}),
            vars=Namespace({"status": Namespace({"start": None, "text": None})}),
            permsloader=PermsLoader(perms_file),
        )
        bot = Bot(context, test_mode=True, test_guild_id=guild_id)
        bot.messenger.msg_owner = AsyncMock()
        task = asyncio.create_task(bot.start(config["DISCORD_TEST_BOT_TOKEN"]))

        guild = None
        test_user = None
        test_role = None
        added_role = False
        original_nick = None
        original_avatar = None
        original_avatar_key = None
        avatar_changed = False
        insight_message = None
        try:
            await asyncio.wait_for(bot.wait_until_ready(), timeout=90)

            guild = bot.get_guild(guild_id)
            assert guild is not None, "Test bot is not in the configured test guild."
            assert bot.user is not None
            if bot_id is not None:
                assert bot.user.id == bot_id
            assert bot.dman.running_daemons == {}
            assert set(bot.extensions) == set(bot.discovered_cogs)
            assert set(bot.tree.loaded_modules) == set(bot.tree.modules)
            assert bot.loaded_command_count > 0

            owner = guild.get_member(owner_id) or await guild.fetch_member(owner_id)
            test_user = guild.get_member(user_id) or await guild.fetch_member(user_id)
            test_role = guild.get_role(role_id)
            if test_role is None:
                test_role = next(
                    (role for role in await guild.fetch_roles() if role.id == role_id),
                    None,
                )
            assert test_role is not None, "Configured test role is not in the guild."

            channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
            assert isinstance(channel, discord.TextChannel)
            assert channel.guild.id == guild.id
            insights_channel = discord.utils.get(
                guild.text_channels, name="user-insights"
            )
            assert insights_channel is not None

            commands = await bot.tree.fetch_commands(guild=discord.Object(id=guild_id))
            names = {command.name for command in commands}
            local_names = {command.name for command in bot.tree.get_commands()}
            assert local_names <= names
            assert {"perms_view", "get_log_channels", "loaded_commands"} <= names
            assert len(names) == len(set(names))

            owner_interaction = _interaction(bot, guild, channel, owner)
            user_interaction = _interaction(bot, guild, channel, test_user)
            await auth_app.perms_view.callback(owner_interaction)
            owner_interaction.response.send_message.assert_awaited_once()
            assert owner_interaction.response.send_message.await_args.kwargs[
                "ephemeral"
            ]

            context_key, guild_permissions = bot.permsloader.ensure_guild(guild.id)
            bot.perms[context_key] = guild_permissions
            assert not bot.perms_check(user_interaction, perm="drive")
            assert not bot.perms_check(user_interaction, perm="privileged")

            original_units = OnMessage.units
            OnMessage.units = {}
            try:
                log_command = bot.tree.get_command("get_log_channels")
                assert log_command is not None
                bot.permsloader.allow_command(context_key, log_command.name)
                await _run_checks(log_command, owner_interaction)
                await log_command.callback(owner_interaction)
                owner_interaction.followup.send.assert_awaited_once()
                assert (
                    owner_interaction.followup.send.await_args.kwargs["embed"].title
                    == "Log Channels"
                )
            finally:
                OnMessage.units = original_units

            loaded_command = bot.tree.get_command("loaded_commands")
            assert loaded_command is not None
            with pytest.raises(app_commands.CheckFailure, match="not allowed"):
                await _run_checks(loaded_command, user_interaction)

            await auth_app.command_allow.callback(user_interaction, "shell")
            assert (
                "need"
                in user_interaction.response.send_message.await_args.args[0].lower()
            )
            user_interaction.response.send_message.reset_mock()

            await auth_app.command_allow.callback(owner_interaction, "loaded_commands")
            await _run_checks(loaded_command, user_interaction)
            await loaded_command.callback(user_interaction)
            assert "Loaded" in user_interaction.response.send_message.await_args.args[0]
            await auth_app.command_disallow.callback(
                owner_interaction, "loaded_commands"
            )
            with pytest.raises(app_commands.CheckFailure, match="not allowed"):
                await _run_checks(loaded_command, user_interaction)

            if test_role not in test_user.roles:
                await test_user.add_roles(
                    test_role, reason="Temporary live test permission"
                )
                added_role = True
                test_user = await guild.fetch_member(user_id)
                user_interaction = _interaction(bot, guild, channel, test_user)
            bot.permsloader.grant(context_key, "drive", "r", role_id)
            bot.permsloader.grant(context_key, "privileged", "r", role_id)
            assert bot.perms_check(user_interaction, perm="drive")
            assert bot.perms_check(user_interaction, perm="privileged")

            await auth_app.command_allow.callback(owner_interaction, "download")
            download_command = bot.tree.get_command("download")
            upload_command = bot.tree.get_command("upload")
            assert download_command is not None and upload_command is not None
            await _run_checks(download_command, user_interaction)
            await _run_checks(upload_command, user_interaction)

            attachment = SimpleNamespace(
                filename="live-upload.txt",
                save=AsyncMock(
                    side_effect=lambda path: Path(path).write_text(
                        "temporary Discord drive upload"
                    )
                ),
            )
            await upload_command.callback(user_interaction, None, attachment)
            uploaded_path = tmp_path / attachment.filename
            assert uploaded_path.read_text() == "temporary Discord drive upload"

            user_interaction.followup.send.reset_mock()
            await download_command.callback(user_interaction, uploaded_path.name)
            downloaded_file = user_interaction.followup.send.await_args.kwargs["file"]
            try:
                assert downloaded_file.fp.read() == b"temporary Discord drive upload"
            finally:
                downloaded_file.close()

            bot.permsloader.revoke(context_key, "drive", "r", role_id)
            with pytest.raises(app_commands.CheckFailure, match="drive"):
                await _run_checks(download_command, user_interaction)

            await auth_app.perms_revoke.callback(
                owner_interaction,
                app_commands.Choice(name="privileged", value="privileged"),
                test_role,
            )
            assert not bot.perms_check(user_interaction, perm="privileged")
            with pytest.raises(app_commands.CheckFailure, match="privileged"):
                await _run_checks(shell_app.shell, user_interaction)

            bot.permsloader.grant(context_key, "privileged", "r", role_id)
            shell_path = tmp_path / "shell-output.txt"
            shell_command = (
                f"printf 'sandbox-shell-ok' > {quote(str(shell_path))} "
                f"&& cat {quote(str(shell_path))}"
            )
            await _run_checks(shell_app.shell, user_interaction)
            shell_message = AsyncMock()
            user_interaction.followup.send.return_value = shell_message
            await shell_app.shell.callback(user_interaction, shell_command)
            assert shell_path.read_text() == "sandbox-shell-ok"
            shell_message.add_reaction.assert_awaited_once_with("🟢")

            original_nick = guild.me.nick
            nickname_command = bot.tree.get_command("set_server_nickname")
            avatar_command = bot.tree.get_command("set_server_avatar")
            assert nickname_command is not None and avatar_command is not None
            await _run_checks(nickname_command, owner_interaction)
            await _run_checks(avatar_command, owner_interaction)
            await guild_app.set_server_nickname.callback(
                owner_interaction, "Cynthia-test-suite"
            )
            assert (await guild.fetch_member(bot.user.id)).nick == "Cynthia-test-suite"

            previous_avatar = guild.me.guild_avatar
            original_avatar_key = previous_avatar.key if previous_avatar else None
            original_avatar = await previous_avatar.read() if previous_avatar else None
            avatar_file = SimpleNamespace(
                content_type="image/png",
                read=AsyncMock(return_value=_png_fixture()),
            )
            owner_interaction.followup.send.reset_mock()
            await guild_app.set_server_avatar.callback(
                owner_interaction, avatar_file, None
            )
            updated_bot_member = await guild.fetch_member(bot.user.id)
            updated_avatar_key = (
                updated_bot_member.guild_avatar.key
                if updated_bot_member.guild_avatar
                else None
            )
            avatar_changed = updated_avatar_key != original_avatar_key
            avatar_reply = owner_interaction.followup.send.await_args.args[0]
            if "avatar too fast" in avatar_reply:
                assert not avatar_changed
            else:
                assert avatar_changed
                assert (
                    avatar_reply
                    == "Successfully changed my profile picture for this server!"
                )

            user = await bot.fetch_user(test_user.id)
            insight_view_message = await insights_channel.send(
                view=InsightView(user, test_user)
            )
            insight_message = insight_view_message

            temporary_command = app_commands.Command(
                name="cynthia-test-probe",
                description="Temporary live command registration test",
                callback=_probe_callback,
            )
            bot.tree.add_command(temporary_command)
            try:
                await bot._sync_command_tree()
                registered = await bot.tree.fetch_commands(
                    guild=discord.Object(id=guild.id)
                )
                assert "cynthia-test-probe" in {command.name for command in registered}
            finally:
                bot.tree.remove_command("cynthia-test-probe")
                bot.tree.remove_command(
                    "cynthia-test-probe", guild=discord.Object(id=guild.id)
                )
                await bot._sync_command_tree()
            unregistered = await bot.tree.fetch_commands(
                guild=discord.Object(id=guild.id)
            )
            assert "cynthia-test-probe" not in {
                command.name for command in unregistered
            }

            bot.tree.sync = AsyncMock()
            await cogs_app.reload_cog.callback(
                owner_interaction, "cynthia.bot.cogs.bouncer"
            )
            assert "Reloaded" in owner_interaction.followup.send.await_args.args[0]
            owner_interaction.followup.send.reset_mock()
            await apps_app.reload_app.callback(owner_interaction, "auth")
            assert (
                "Reloaded `auth`" in owner_interaction.followup.send.await_args.args[0]
            )
            assert bot.tree.sync.await_count == 2
        finally:
            if insight_message is not None:
                await insight_message.delete()
            if added_role and test_user is not None and test_role is not None:
                await test_user.remove_roles(
                    test_role, reason="Restore role after temporary live test"
                )
            if guild is not None and original_nick is not None:
                await guild.me.edit(
                    nick=original_nick, reason="Restore nickname after live test"
                )
            if guild is not None and avatar_changed:
                await guild.me.edit(
                    avatar=original_avatar,
                    reason="Restore avatar after live test",
                )
            await bot.close()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())
