import discord
from pathlib import Path
from discord import app_commands
from typing import Optional


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


__application__ = [upload, download]
