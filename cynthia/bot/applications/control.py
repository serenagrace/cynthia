import discord
from typing import Literal
from discord import app_commands
from cynthia.exceptions import ExitCynthia
from cynthia.utils.auth import privileged_only


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


__application__ = [shutdown, restart, upgrade, reload]
