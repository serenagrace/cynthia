import discord
from pathlib import Path
from discord import app_commands
from typing import Optional


@app_commands.command()
async def verify(interaction: discord.Interaction, code: app_commands.Range[str, 6, 6]):
    await interaction.response.send_message(
        interaction.client.verify(code), ephemeral=True
    )


__application__ = [verify]
