import discord
from discord import app_commands
from cynthia.utils.auth import nonglobal_command, is_owner


@app_commands.command()
@app_commands.default_permissions(administrator=True)
@is_owner()
@nonglobal_command()
async def verify(interaction: discord.Interaction, code: app_commands.Range[str, 6, 6]):
    await interaction.response.send_message(
        interaction.client.verify(code), ephemeral=True
    )


__application__ = [verify]
