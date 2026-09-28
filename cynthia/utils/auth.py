import pyotp
import discord
from typing import Callable
from discord import app_commands


def verify_factory(secret: str) -> Callable[[str], bool]:
    def verify(code: str) -> bool:
        totp = pyotp.TOTP(secret)
        return totp.verify(code)

    return verify


def is_owner(strict: bool = True):
    async def predicate(interaction: discord.Interaction) -> bool:
        if strict:
            return interaction.user.id == interaction.client.owner
        return interaction.client.perms_check(interaction, perm="owner")

    return app_commands.check(predicate)


def privileged_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        return interaction.client.perms_check(interaction, perm="privileged")

    return app_commands.check(predicate)


def nxbt_permission():
    async def predicate(interaction: discord.Interaction) -> bool:
        return interaction.client.perms_check(interaction, perm="nxbt")

    return app_commands.check(predicate)


def drive_permission():
    async def predicate(interaction: discord.Interaction) -> bool:
        return interaction.client.perms_check(interaction, perm="drive")

    return app_commands.check(predicate)


def nonglobal_command():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            return True
        return interaction.client.perms_check(
            interaction, perm="allowed_commands", command=interaction.command.name
        )

    return app_commands.check(predicate)
