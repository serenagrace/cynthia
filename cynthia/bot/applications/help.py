import discord
from discord import app_commands


@app_commands.command()
async def help(interaction: discord.Interaction):
    await interaction.response.defer()
    commands = await interaction.client.tree.fetch_commands()
    available_commands = []
    for cmd in commands:
        command = interaction.client.tree.get_command(cmd.name)
        if await command.can_run(interaction):
            available_commands.append(f"- /{cmd.name}")
    if available_commands:
        help_message = "Available commands:\n" + "\n".join(available_commands)
    else:
        help_message = "No available commands. You may not have permission."
    await interaction.response.followup.send(help_message)


__application__ = [help]
