import discord
from discord import app_commands

from cynthia.daemons.dman import DMan
from cynthia.utils.auth import is_owner


@app_commands.command()
@app_commands.describe(daemon="Daemon to reload")
@app_commands.choices(
    daemon=[app_commands.Choice(name=name, value=name) for name in DMan.RELOADABLE]
)
@app_commands.dm_only()
@is_owner()
async def reload_daemon(
    interaction: discord.Interaction, daemon: app_commands.Choice[str]
):
    await interaction.response.defer(thinking=True, ephemeral=True)
    try:
        await interaction.client.dman.reload_daemon(daemon.value)
    except Exception as e:
        await interaction.followup.send(f"Failed to reload `{daemon.value}`: {e}")
        return
    await interaction.followup.send(f"Reloaded `{daemon.value}`.")


__application__ = [reload_daemon]
