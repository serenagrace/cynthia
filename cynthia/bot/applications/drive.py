import discord
from pathlib import Path
from discord import app_commands
from typing import Optional
from datetime import datetime


@app_commands.command()
async def upload(
    interaction: discord.Interaction,
    filename: Optional[str],
    attachment: discord.Attachment,
) -> None:
    interaction.response.defer()
    drive_path = interaction.client.config.get("drive_path", None)
    if drive_path is None:
        await interaction.followup.send("Drive path not configured.")
        return
    if not Path(drive_path).exists():
        await interaction.followup.send("Drive path does not exist.")
        return
    if not Path(drive_path).is_dir():
        await interaction.followup.send("Drive path is not a directory.")
        return
    if filename is None:
        filename = attachment.filename
    save_path = Path(drive_path) / filename
    try:
        await attachment.save(save_path)
        await interaction.followup.send(f"File uploaded to {save_path}.")
    except Exception as e:
        await interaction.followup.send(f"Failed to upload file: {e}")
    return


@app_commands.context_menu(name="Upload to Drive")
async def upload_context_menu(interaction: discord.Interaction, message: discord.Message):
    await interaction.response.defer()
    drive_path = interaction.client.config.get("drive_path", None)
    if drive_path is None:
        await interaction.followup.send("Drive path not configured.")
        return
    if not Path(drive_path).exists():
        await interaction.followup.send("Drive path does not exist.")
        return
    if not Path(drive_path).is_dir():
        await interaction.followup.send("Drive path is not a directory.")
        return
    if not message.attachments:
        content = message.content
        save_path = Path(drive_path) / f"message_{message.id}.txt"
        try:
            with open(save_path, "w") as f:
                f.write(content)
            await interaction.followup.send(f"Message id {message.id} content saved to `{str(save_path)}`.")
        except Exception as e:
            await interaction.followup.send(f"Failed to save message content: {e}")
        return
    attachment = message.attachments[0]
    save_path = Path(drive_path) / attachment.filename
    with open(save_path, "w") as f:
        await attachment.save(f)
    await interaction.followup.send(f"Attachment saved to {save_path}.")

@app_commands.command()
async def download(interaction: discord.Interaction, filename: str):
    interaction.response.defer()
    drive_path = interaction.client.config.get("drive_path", None)
    if drive_path is None:
        await interaction.followup.send("Drive path not configured.")
        return
    if not Path(drive_path).exists():
        await interaction.followup.send("Drive path does not exist.")
        return
    if not Path(drive_path).is_dir():
        await interaction.followup.send("Drive path is not a directory.")
        return
    file_path = Path(drive_path) / filename
    if not file_path.exists():
        await interaction.followup.send("File does not exist.")
        return
    if not file_path.is_file():
        await interaction.followup.send("Specified path is not a file.")
        return
    try:
        await interaction.followup.send(file=discord.File(file_path))
    except Exception as e:
        await interaction.followup.send(f"Failed to download file: {e}")


__application__ = [upload, download, upload_context_menu]
