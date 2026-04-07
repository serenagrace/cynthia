import pyotp
import discord
from typing import Callable
from discord import app_commands


def verify_factory(secret: str) -> Callable[[str], bool]:
    def verify(code: str) -> bool:
        totp = pyotp.TOTP(secret)
        return totp.verify(code)

    return verify


def privileged_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id in interaction.client.config.privileged_users:
            return True
        return False
    return app_commands.check(predicate)


def nxbt_permission():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id in interaction.client.config.nxbt_users:
            return True
        return False
    return app_commands.check(predicate)


def drive_permission():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id in interaction.client.config.drive_users:
            return True
        return False
    return app_commands.check(predicate)
