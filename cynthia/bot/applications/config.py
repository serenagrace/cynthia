import discord
from discord import app_commands


@app_commands.command()
async def cget(interaction: discord.Interaction, key: str):
    value = interaction.client.config.get(key, discord.utils.MISSING)
    if value is discord.utils.MISSING:
        await interaction.response.send_message(
            f"Invalid key `{key}` not found in config."
        )
    else:
        await interaction.response.send_message(value)


@app_commands.command()
@app_commands.rename(val="value")
async def cset(
    interaction: discord.Interaction,
    key: str,
    val: str,
    force: bool = False,
    reload: bool = False,
):
    value = interaction.client.config.get(key, discord.utils.MISSING)
    if value is discord.utils.MISSING:
        if not force:
            await interaction.response.send_message(
                f"Invalid key `{key}` not found in config."
            )
        else:
            interaction.client.config.set(key, val)
            await interaction.response.send_message("(!) Config updated.")
    else:
        interaction.client.config.set(key, val)
        await interaction.response.send_message("Config updated.")
    if reload:
        pass  # TODO


__application__ = [cset, cget]
