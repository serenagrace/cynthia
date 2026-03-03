import discord
from pathlib import Path
from discord import app_commands
from tempfile import TemporaryFile
from cynthia.utils.auth import privileged_only
import subprocess


@app_commands.command()
@privileged_only()
async def shell(interaction: discord.Interaction, command: str):
    await interaction.response.defer()
    message = None
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        if result.stdout:
            if len(result.stdout) > 1999:
                with TemporaryFile(mode="w+", encoding="utf-8") as temp_file:
                    temp_file.write(result.stdout)
                    temp_file.seek(0)
                    message = await interaction.followup.send(
                        file=discord.File(temp_file, filename="output.txt")
                    )
            else:
                message = await interaction.followup.send(f"```{result.stdout}```")
        else:
            message = await interaction.followup.send(
                "*(Command executed with no output.)*"
            )
        if message is not None:
            if not result.returncode:
                await message.add_reaction("🟢")  # Green circle
            else:
                await message.add_reaction("🔴")  # Red circle
    except Exception as e:
        await interaction.followup.send(f"Failed to execute command: {e}")


__application__ = [shell]
