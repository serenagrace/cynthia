"""Guild-only commands for changing the bot's server profile."""

import aiohttp
import discord
from discord import app_commands


@app_commands.command()
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def set_server_avatar(
    interaction: discord.Interaction, file: discord.Attachment = None, url: str = None
):
    """Set the bot's server avatar from an image attachment or URL."""
    # 1. Check if the user uploaded an image or provided a URL
    avatar_bytes = b""
    if url is None and file is None:
        return await interaction.response.send_message(
            "Please provide an image URL or upload an image file."
        )
    if file and url:
        return await interaction.response.send_message(
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
                        return await interaction.followup.send(
                            "Failed to download the image. Check the URL."
                        )
                    avatar_bytes = await response.read()

        await interaction.guild.me.edit(avatar=avatar_bytes)
        await interaction.followup.send(
            "Successfully changed my profile picture for this server!"
        )

    except discord.Forbidden:
        await interaction.followup.send(
            "I don't have permission to change my profile here. Make sure my role is high enough!"
        )
    except discord.HTTPException as e:
        await interaction.followup.send(
            f"Failed to change avatar: `{e.text}`. (Note: Discord limits how frequently you can update profiles)."
        )
    except Exception as e:
        await interaction.followup.send(f"An unexpected error occurred: {e}")


@app_commands.command()
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def set_server_nickname(interaction: discord.Interaction, nickname: str = None):
    """Set the bot's nickname in the current server."""
    if nickname is None:
        nickname = "Cynthia"
    await interaction.guild.me.edit(nick=nickname)
    await interaction.response.send_message(
        f"Successfully changed my nickname to `{nickname}` for this server!"
    )


__application__ = [set_server_avatar, set_server_nickname]
