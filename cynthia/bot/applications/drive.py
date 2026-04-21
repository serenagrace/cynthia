import discord
from pathlib import Path
from discord import app_commands
from typing import Optional
from datetime import datetime
from cynthia.utils.auth import drive_permission


@app_commands.command()
@drive_permission()
async def upload(
    interaction: discord.Interaction,
    filename: Optional[str],
    attachment: discord.Attachment,
) -> None:
    await interaction.response.defer(ephemeral=True)
    if not interaction.client.drive.enabled:
        await interaction.followup.send("Drive path not configured.")
        return
    if filename is None:
        filename = attachment.filename
    save_path = interaction.client.drive.path(filename)
    try:
        await attachment.save(save_path)
        await interaction.followup.send(f"File uploaded to {save_path}.")
    except Exception as e:
        await interaction.followup.send(f"Failed to upload file: {e}")
    return


@app_commands.context_menu(name="Upload to Drive")
@drive_permission()
async def upload_context_menu(
    interaction: discord.Interaction, message: discord.Message
):
    await interaction.response.defer(ephemeral=True)
    if not interaction.client.drive.enabled:
        await interaction.followup.send("Drive path not configured.")
        return
    if not message.attachments:
        content = message.content
        try:
            with interaction.client.drive.open(f"message_{message.id}.txt", "w") as f:
                f.write(content)
            await interaction.followup.send(
                f"Message id {message.id} content saved to `{str(save_path)}`."
            )
        except Exception as e:
            await interaction.followup.send(f"Failed to save message content: {e}")
        return
    attachment = message.attachments[0]
    with interaction.client.drive.open(save_path, "w") as f:
        await attachment.save(f)
    await interaction.followup.send(f"Attachment saved to {save_path}.")


@app_commands.command()
@drive_permission()
async def download(interaction: discord.Interaction, filename: str):
    interaction.response.defer()
    if not interaction.client.drive.enabled:
        await interaction.followup.send("Drive path not configured.")
        return
    file_path = interaction.client.drive.path(filename)
    if not interaction.client.drive.exists(filename, is_file=True):
        await interaction.followup.send("Specified path is not a file.")
        return
    try:
        await interaction.followup.send(file=discord.File(file_path))
    except Exception as e:
        await interaction.followup.send(f"Failed to download file: {e}")


__application__ = [upload, download, upload_context_menu]
