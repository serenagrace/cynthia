"""Commands for discovering and reloading bot cogs."""

import discord
from discord import app_commands

from cynthia.utils.auth import is_owner


async def cog_autocomplete(interaction: discord.Interaction, current: str):
    """Suggest discovered cogs matching the user's query."""
    prefix = "cynthia.bot.cogs."
    return [
        app_commands.Choice(name=c.removeprefix(prefix), value=c)
        for c in sorted(interaction.client.discovered_cogs)
        if current.lower() in c.lower()
    ][:25]


@app_commands.command()
@app_commands.describe(cog="Cog to reload")
@app_commands.autocomplete(cog=cog_autocomplete)
@app_commands.dm_only()
@is_owner()
async def reload_cog(interaction: discord.Interaction, cog: str):
    """Reload one discovered cog and report the result privately."""
    await interaction.response.defer(thinking=True, ephemeral=True)
    error = await interaction.client.reload_cog(cog)
    if error:
        await interaction.followup.send(
            f"❌ Reload of `{cog}` failed; kept the previous version.\n```{error[:1500]}```"
        )
        return
    await interaction.followup.send(f"✅ Reloaded `{cog}`.")


__application__ = [reload_cog]
