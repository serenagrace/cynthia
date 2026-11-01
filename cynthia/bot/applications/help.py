"""Command for listing application commands available to the caller."""

import asyncio
import logging

import discord
from discord import app_commands

from cynthia.utils.embeds import make_embed

logger = logging.getLogger(__name__)


async def run_check(check: callable, interaction: discord.Interaction) -> bool:
    """Run a command check, awaiting it when it is asynchronous."""
    if asyncio.iscoroutinefunction(check):
        return await check(interaction)
    else:
        return check(interaction)


@app_commands.command()
async def help(interaction: discord.Interaction):
    """List commands whose permission checks pass for this interaction."""
    await interaction.response.defer()
    commands = await interaction.client.tree.fetch_commands()
    available_commands = []
    for cmd in commands:
        command = interaction.client.tree.get_command(cmd.name)
        if not command:
            continue
        checks = command.checks
        if command.checks:
            if all(
                await asyncio.gather(
                    *[run_check(check, interaction) for check in checks]
                )
            ):
                logger.debug("Command passed checks: %s", cmd.name)
                available_commands.append(f"- /{cmd.name}")
        else:
            logger.debug("Command has no checks: %s", cmd.name)
            available_commands.append(f"- /{cmd.name}")
    if not available_commands:
        await interaction.followup.send(
            "No available commands. You may not have permission."
        )
        return
    embed = make_embed("Available commands", "\n".join(available_commands)[:4096])
    await interaction.followup.send(embed=embed)


__application__ = [help]
