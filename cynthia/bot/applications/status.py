import discord
from discord import app_commands
import asyncio


async def ping_status(host: str) -> list:
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
    return {
        "service": name,
        "color": "green" if value else "red",
        "code": 0 if value else 1,
        "msg": "True" if value else "False"
    }


async def gather_results(client):
    tasks = [
        systemctl_status("pihole-FTL.service"),
        ping_status("discord.com"),
        ping_status("github.com"),
        ping_status("google.com"),
        ping_status("ALVIS"),
        ping_status("rokutv"),
        bool_status("Drive Available", client.logging_enabled),
    ]

    results = []
    # Process results as soon as they finish
    for task in asyncio.as_completed(tasks):
        result = await task
        results.append(result)

    return results


@app_commands.command()
async def status(interaction: discord.Interaction):
    await interaction.response.defer()
    final_statuses = await gather_results(interaction.client)
    message = "\n".join(
        [
            f" - :{status['color']}_circle: {status['service']}"
            for status in final_statuses
        ]
    )
    await interaction.followup.send(message)

@app_commands.command()
async def loaded_modules(interaction: discord.Interaction):
    await interaction.client.messenger.send_list(interaction, f"Loaded ({len(interaction.client.tree.loaded_modules)}/{len(interaction.client.tree.modules)}) Modules:", interaction.client.tree.loaded_modules)

@app_commands.command()
async def loaded_commands(interaction: discord.Interaction):
    await interaction.client.messenger.send_list(interaction, f"Loaded {len(interaction.client.tree.loaded_commands)} Commands:", interaction.client.tree.loaded_commands)


__application__ = [status, loaded_modules, loaded_commands]
