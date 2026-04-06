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
        if interaction.user.id not in interaction.client.config.privileged_users:
            await interaction.response.send_message(
                "You do not have permission to use this command.", ephemeral=True
            )
            return False
        return True

    return app_commands.check(predicate)
