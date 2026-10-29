"""Commands and helpers for checking service and host status."""

import asyncio

import discord
from discord import app_commands

from cynthia.utils.auth import is_owner, nonglobal_command

# Pinged when STATUS_HOSTS is not set in .env
DEFAULT_HOSTS = ["discord.com", "github.com", "google.com"]


async def ping_status(host: str) -> list:
    """Ping a host and return a status record for the result."""
    # Adding a timeout here is the best way to prevent 'hanging'
    proc = await asyncio.create_subprocess_exec(
        "ping",
        "-c",
        "4",
        "-W",
        "0.33",
        host,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    status_code = proc.returncode
    return {
        "service": f"ping {host}",
        "color": "green" if status_code == 0 else "red",
        "code": status_code,
        "msg": "reachable" if status_code == 0 else "unreachable",
    }


async def systemctl_status(service: str) -> list:
    """Check whether a systemd service is active and return its status."""
    proc = await asyncio.create_subprocess_exec(
        "systemctl",
        "is-active",
        service,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    status_code = proc.returncode
    msg = "active" if status_code == 0 else "inactive"
    return {
        "service": service,
        "color": "green" if status_code == 0 else "red",
        "code": status_code,
        "msg": msg,
    }


async def bool_status(name: str, value: bool):
    """Convert a boolean value into a standard status record."""
    return {
        "service": name,
        "color": "green" if value else "red",
        "code": 0 if value else 1,
        "msg": "True" if value else "False",
    }


async def gather_results(client):
    """Collect configured service, host, and drive status records."""
    tasks = [
        *(systemctl_status(service) for service in client.config.status_services),
        *(ping_status(host) for host in client.status_hosts or DEFAULT_HOSTS),
        bool_status("Drive Available", client.logging_enabled),
    ]

    results = []
    # Process results as soon as they finish
    for task in asyncio.as_completed(tasks):
        result = await task
        results.append(result)

    return results


@app_commands.command()
@is_owner()
@app_commands.dm_only()
async def status(interaction: discord.Interaction):
    """Show service health results to the bot owner."""
    await interaction.response.defer()
    final_statuses = await gather_results(interaction.client)
    description = "\n".join(
        [f":{status['color']}_circle: {status['service']}" for status in final_statuses]
    )
    embed = discord.Embed(
        title="Service Status",
        description=description,
        color=0xD700FF,
    )
    await interaction.followup.send(embed=embed)


@app_commands.command()
@nonglobal_command()
@app_commands.default_permissions(administrator=True)
async def loaded_modules(interaction: discord.Interaction):
    """List application modules loaded by the command tree."""
    await interaction.client.messenger.send_list(
        interaction,
        f"Loaded ({len(interaction.client.tree.loaded_modules)}/{len(interaction.client.tree.modules)}) Modules:",
        interaction.client.tree.loaded_modules,
    )


@app_commands.command()
@nonglobal_command()
@app_commands.default_permissions(administrator=True)
async def loaded_commands(interaction: discord.Interaction):
    """List application commands loaded by the command tree."""
    await interaction.client.messenger.send_list(
        interaction,
        f"Loaded {len(interaction.client.tree.loaded_commands)} Commands:",
        interaction.client.tree.loaded_commands,
    )


@app_commands.command()
@app_commands.dm_only()
@is_owner()
async def set_status(
    interaction: discord.Interaction, description: str, time: bool = True
):
    """Set the bot's Discord status."""
    interaction.client.vars.status.text = description
    interaction.client.vars.status.start = discord.utils.utcnow() if time else None
    await interaction.response.send_message("Bot status updated.", ephemeral=True)


@app_commands.command()
@app_commands.dm_only()
@is_owner()
async def clear_status(interaction: discord.Interaction):
    """Clear the bot's Discord status."""
    interaction.client.vars.status.text = None
    interaction.client.vars.status.start = None
    await interaction.response.send_message("Bot status cleared.", ephemeral=True)


__application__ = [status, loaded_modules, loaded_commands, set_status, clear_status]
