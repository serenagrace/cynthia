import discord
from typing import Literal
from discord import app_commands
from exceptions import ExitCynthia


@app_commands.command()
async def shutdown(interaction: discord.Interaction):
    await interaction.response.send_message("Shutting down...")
    try:
        raise ExitCynthia("Shutdown")
    except ExitCynthia as e:
        await interaction.client.__aexit__(type(e), e, e.__traceback__)


@app_commands.command()
async def restart(interaction: discord.Interaction):
    pass


@app_commands.command()
async def upgrade(interaction: discord.Interaction):
    pass


__application__ = [shutdown, restart, upgrade]
