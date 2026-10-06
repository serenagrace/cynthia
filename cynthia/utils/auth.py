import pyotp
import functools
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
            return str(interaction.user.id) == interaction.client.owner
        return interaction.client.perms_check(interaction, perm="owners")

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


def button_requires_role(role_name):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(
            self, interaction: discord.Interaction, button: discord.ui.Button
        ):
            if isinstance(role_name, str):
                role_names = [role_name.lower()]
            else:
                role_names = [r_name.lower() for r_name in role_name]

            if not any(
                role.name.lower() in role_names for role in interaction.user.roles
            ):
                await interaction.response.send_message(
                    "You do not have the required role to use this button.",
                    ephemeral=True,
                )
                return
            return await func(self, interaction, button)

        return wrapper

    return decorator


def button_requires_permission(**perms):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(
            self, interaction: discord.Interaction, button: discord.ui.Button
        ):
            # Check if the interaction occurred inside a server
            if not interaction.guild or not isinstance(
                interaction.user, discord.Member
            ):
                await interaction.response.send_message(
                    "❌ This button can only be used inside a server!", ephemeral=True
                )
                return
            # interaction.permissions evaluates the member's resolved permissions in the channel
            user_perms = interaction.permissions

            # Verify that all required permissions are True
            missing_perms = [
                perm.replace("_", " ").title()
                for perm, required in perms.items()
                if required and not getattr(user_perms, perm, False)
            ]

            if missing_perms:
                perm_list = ", ".join(f"**{p}**" for p in missing_perms)
                await interaction.response.send_message(
                    f"❌ You lack the required permission(s) to use this button: {perm_list}",
                    ephemeral=True,
                )
                return
            return await func(self, interaction, button)

        return wrapper

    return decorator
