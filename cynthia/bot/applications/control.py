import discord
from discord import app_commands
from cynthia.exceptions import ExitCynthia
from cynthia.utils.auth import privileged_only, is_owner
from cynthia.utils.onmessage import OnMessage
import aiohttp


@app_commands.command()
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def set_server_avatar(
    interaction: discord.Interaction, file: discord.Attachment = None, url: str = None
):
    # 1. Check if the user uploaded an image or provided a URL
    avatar_bytes = b""
    if url is None and file is None:
        return await interaction.send(
            "Please provide an image URL or upload an image file."
        )
    if file and url:
        return await interaction.send(
            "Please provide either an image URL or upload an image file, not both."
        )

    await interaction.response.defer(thinking=True, ephemeral=True)

    try:
        if file:
            if not file.content_type or not file.content_type.startswith("image/"):
                return await interaction.followup.send(
                    "⚠️ The uploaded file must be an image (PNG, JPEG, GIF)."
                )
            avatar_bytes = await file.read()
        if url:
            # 2. Download the image as a bytes-like object
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        return await interaction.send(
                            "Failed to download the image. Check the URL."
                        )
                    avatar_bytes = await response.read()

        await interaction.guild.me.edit(avatar=avatar_bytes)
        await interaction.followup.send_message(
            "Successfully changed my profile picture for this server!"
        )

    except discord.Forbidden:
        await interaction.send(
            "I don't have permission to change my profile here. Make sure my role is high enough!"
        )
    except discord.HTTPException as e:
        await interaction.send(
            f"Failed to change avatar: `{e.text}`. (Note: Discord limits how frequently you can update profiles)."
        )
    except Exception as e:
        await interaction.send(f"An unexpected error occurred: {e}")


@app_commands.command()
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def set_server_nickname(interaction: discord.Interaction, nickname: str = None):
    if nickname is None:
        nickname = "Cynthia"
    await interaction.guild.me.edit(nick=nickname)
    await interaction.response.send(
        f"Successfully changed my nickname to `{nickname}` for this server!"
    )


@app_commands.command()
@is_owner()
@app_commands.default_permissions(administrator=True)
async def shutdown(interaction: discord.Interaction):
    await interaction.response.send_message("Shutting down...")
    try:
        raise ExitCynthia("Shutdown")
    except ExitCynthia as e:
        await interaction.client.__aexit__(type(e), e, e.__traceback__)


@app_commands.command()
@is_owner()
@app_commands.default_permissions(administrator=True)
async def restart(interaction: discord.Interaction):
    await interaction.response.send_message("Restarting...")
    try:
        raise ExitCynthia("Restart")
    except ExitCynthia as e:
        await interaction.client.__aexit__(type(e), e, e.__traceback__)


@app_commands.command()
@is_owner()
@app_commands.default_permissions(administrator=True)
async def reload(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    await interaction.client.reload_tree(interaction)


@app_commands.command()
@is_owner()
@app_commands.default_permissions(administrator=True)
async def upgrade(interaction: discord.Interaction):
    pass


@app_commands.command()
@is_owner()
@app_commands.default_permissions(administrator=True)
async def log_channel(interaction: discord.Interaction):
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
    shutdown,
    restart,
    upgrade,
    reload,
    log_channel,
    stop_log_channel,
    get_log_channels,
    set_server_avatar,
    set_server_nickname,
]
