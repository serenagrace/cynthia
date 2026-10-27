import discord
from discord import app_commands

from cynthia.utils.auth import is_owner


@app_commands.command()
@is_owner()
@app_commands.dm_only()
async def reload(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    await interaction.client.reload_tree(interaction)


async def application_autocomplete(interaction: discord.Interaction, current: str):
    return [
        app_commands.Choice(name=m, value=m)
        for m in sorted(interaction.client.tree.modules)
        if current.lower() in m.lower()
    ][:25]


@app_commands.command()
@app_commands.describe(module="Application module to reload")
@app_commands.autocomplete(module=application_autocomplete)
@app_commands.dm_only()
@is_owner()
async def reload_app(interaction: discord.Interaction, module: str):
    await interaction.response.defer(thinking=True, ephemeral=True)
    errors = await interaction.client.reload_application(module)
    if errors:
        await interaction.followup.send(
            f"❌ Reload of `{module}` failed; kept previous commands.\n```{errors[0][:1500]}```"
        )
        return
    await interaction.followup.send(f"✅ Reloaded `{module}` and synced commands.")


__application__ = [reload, reload_app]
