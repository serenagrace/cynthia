"""Owner commands for bot lifecycle and message-log channel management."""

import asyncio
import logging

import discord
from discord import app_commands

from cynthia.exceptions import ExitCynthia
from cynthia.utils.auth import is_owner
from cynthia.utils.onmessage import OnMessage

logger = logging.getLogger(__name__)


# Time for the goodbye to show in the stream's chat pane before it ends
GOODBYE_SECONDS = 5


def cog(client, name):
    """A loaded cog, or None (also for clients without cogs)."""
    get_cog = getattr(client, "get_cog", None)
    return get_cog(name) if get_cog else None


async def announce(client, key):
    """Post a fixed Twitch chat message; returns whether it went out.

    Never raises or blocks the exit for long.
    """
    chat = cog(client, "LLMChatCog")
    if chat is None:
        return False
    try:
        return await asyncio.wait_for(chat.announce(key), timeout=5)
    except Exception:
        logger.warning("Couldn't post %s to Twitch.", key, exc_info=True)
        return False


async def announce_reboot(client):
    """Tell Twitch chat Cynthia will be right back."""
    await announce(client, "twitch_reboot_message")


async def end_stream(client):
    """Say goodbye in Twitch chat, let it show on stream, then end the stream."""
    if await announce(client, "twitch_goodbye_message"):
        await asyncio.sleep(GOODBYE_SECONDS)
    obs = cog(client, "OBSCog")
    if obs is not None:
        await obs.end_stream()


@app_commands.command()
@is_owner()
@app_commands.dm_only()
async def shutdown(interaction: discord.Interaction):
    """End the Twitch stream with a goodbye, then shut down the bot cleanly."""
    await interaction.response.send_message("Shutting down...")
    await end_stream(interaction.client)
    try:
        raise ExitCynthia("Shutdown")
    except ExitCynthia as e:
        await interaction.client.__aexit__(type(e), e, e.__traceback__)


@app_commands.command()
@is_owner()
@app_commands.dm_only()
async def restart(interaction: discord.Interaction):
    """Shut down the bot and request a process restart."""
    await interaction.response.send_message("Restarting...")
    await announce_reboot(interaction.client)
    try:
        raise ExitCynthia("Restart")
    except ExitCynthia as e:
        await interaction.client.__aexit__(type(e), e, e.__traceback__)


@app_commands.command()
@is_owner()
@app_commands.dm_only()
@app_commands.describe(
    graceful="Shut Cynthia down cleanly, then reboot normally (default: force reboot)"
)
async def reboot(interaction: discord.Interaction, graceful: bool = False):
    """Reboot the host immediately or after a graceful bot shutdown."""
    if graceful:
        await interaction.response.send_message(
            "Shutting down cleanly, then rebooting the host..."
        )
        await announce_reboot(interaction.client)
        try:
            raise ExitCynthia("Reboot")
        except ExitCynthia as e:
            await interaction.client.__aexit__(type(e), e, e.__traceback__)
        return
    await interaction.response.send_message("Rebooting the host now...")
    await announce_reboot(interaction.client)
    # Let the reply go out before the system is killed
    await asyncio.sleep(1)
    await asyncio.create_subprocess_exec("sudo", "-n", "reboot", "-f", "now")


@app_commands.command()
@is_owner()
@app_commands.default_permissions(administrator=True)
async def log_channel(interaction: discord.Interaction):
    """Enable message logging for the current server channel."""
    await interaction.response.defer(thinking=True, ephemeral=True)
    if interaction.channel_id is None or interaction.guild_id is None:
        await interaction.followup.send(
            "This command can only be used in a guild channel."
        )
        return
    key = f"log_{interaction.guild_id}_{interaction.channel_id}"
    if key not in OnMessage.units:
        OnMessage.units[key] = OnMessage(
            logger=getattr(interaction.client, "logger", None),
            channel=interaction.channel,
            guild=interaction.guild,
        )
        await interaction.followup.send(
            "This channel is now set as a log channel. All messages sent here will be logged."
        )
    else:
        await interaction.followup.send(
            "This channel is already a log channel. Messages sent here are being logged."
        )


@app_commands.command()
@is_owner()
@app_commands.default_permissions(administrator=True)
async def stop_log_channel(interaction: discord.Interaction):
    """Disable message logging for the current channel."""
    await interaction.response.defer(thinking=True, ephemeral=True)
    key = f"log_{interaction.guild_id}_{interaction.channel_id}"
    if key in OnMessage.units:
        del OnMessage.units[key]
        await interaction.followup.send(
            "This channel is no longer a log channel. Messages sent here will not be logged."
        )
    else:
        await interaction.followup.send("This channel is not currently a log channel.")


@app_commands.command()
@is_owner()
@app_commands.default_permissions(administrator=True)
async def get_log_channels(interaction: discord.Interaction):
    """List configured message-log channels that remain accessible."""
    await interaction.response.defer(thinking=True, ephemeral=True)
    log_channels = {}
    logged_guilds = 0
    logged_channels = 0
    for key in OnMessage.units.keys():
        if key.startswith("log_"):
            guild_id, channel_id = key.split("_")[1:]
            if int(guild_id) in log_channels.keys():
                log_channels[int(guild_id)].append(int(channel_id))
                logged_channels += 1
            else:
                log_channels[int(guild_id)] = [int(channel_id)]
                logged_guilds += 1
                logged_channels += 1
    if logged_channels > 0:
        description = f"Currently logging {logged_channels} channel{'s' if logged_channels != 1 else ''} across {logged_guilds} guild{'s' if logged_guilds != 1 else ''}.\n\n"
    else:
        description = "No log channels currently set.\n\n"
    embed = discord.Embed(
        title="Log Channels",
        color=0xD700FF,
        description=description,
    )

    for guild_id, channel_ids in log_channels.items():
        guild = interaction.client.get_guild(guild_id)
        if guild is not None:
            channels = []
            for channel_id in channel_ids:
                channel = guild.get_channel(channel_id)
                if channel is not None:
                    channels.append(channel)
            if channels:
                embed.add_field(
                    name=f"{guild.name} ({guild_id}) - {len(channels)} channel{'s' if len(channels) != 1 else ''}",
                    value="\n".join(
                        [f"{channel.name} ({channel.id})" for channel in channels]
                    ),
                    inline=False,
                )

    await interaction.followup.send(embed=embed)


__application__ = [
    reboot,
    shutdown,
    restart,
    log_channel,
    stop_log_channel,
    get_log_channels,
]
