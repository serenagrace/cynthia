import discord
from pathlib import Path
from typing import Literal
from discord import app_commands
from cynthia.exceptions import ExitCynthia
from cynthia.utils.auth import privileged_only
from cynthia.utils.onmessage import OnMessage, ONMESSAGE, save_onmessage


@app_commands.command()
@privileged_only()
async def shutdown(interaction: discord.Interaction):
    await interaction.response.send_message("Shutting down...")
    try:
        raise ExitCynthia("Shutdown")
    except ExitCynthia as e:
        await interaction.client.__aexit__(type(e), e, e.__traceback__)


@app_commands.command()
@privileged_only()
async def restart(interaction: discord.Interaction):
    await interaction.response.send_message("Restarting...")
    save_onmessage(interaction.client.database)
    try:
        raise ExitCynthia("Restart")
    except ExitCynthia as e:
        await interaction.client.__aexit__(type(e), e, e.__traceback__)


@app_commands.command()
@privileged_only()
async def reload(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    await interaction.client.reload_tree(interaction)


@app_commands.command()
@privileged_only()
async def upgrade(interaction: discord.Interaction):
    pass


@app_commands.command()
@privileged_only()
async def log_channel(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    if interaction.channel_id is None or interaction.guild_id is None:
        await interaction.followup.send(
            "This command can only be used in a guild channel."
        )
        return
    key = f"log_{interaction.guild_id}_{interaction.channel_id}"
    if key not in ONMESSAGE:
        ONMESSAGE[key] = OnMessage(
            getattr(interaction.client, "logger", None),
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
@privileged_only()
async def stop_log_channel(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    key = f"log_{interaction.guild_id}_{interaction.channel_id}"
    if key in ONMESSAGE:
        del ONMESSAGE[key]
        await interaction.followup.send(
            "This channel is no longer a log channel. Messages sent here will not be logged."
        )
    else:
        await interaction.followup.send("This channel is not currently a log channel.")


@app_commands.command()
@privileged_only()
async def get_log_channels(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    log_channels = {}
    logged_guilds = 0
    logged_channels = 0
    for key in ONMESSAGE.keys():
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
    shutdown,
    restart,
    upgrade,
    reload,
    log_channel,
    stop_log_channel,
    get_log_channels,
]
