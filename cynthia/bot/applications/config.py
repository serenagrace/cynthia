import discord
from discord import app_commands


class ConfigApplication(app_commands.Group):
    name = "config"


@ConfigApplication.command
async def get(interaction: discord.Interaction, key: str):
    MissingValue = object()
    value = interaction.client.config.get(key, MissingValue)
    if value is MissingValue:
        await interaction.response.send_message(
            f"Invalid key `{key}` not found in config."
        )
    else:
        await interaction.response.send_message(f"config[{key}] = {value}")


__application__ = ConfigApplication
