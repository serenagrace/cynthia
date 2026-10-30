"""Discord command and button permission-check decorators."""

import functools
from typing import Callable

import discord
import pyotp
from discord import app_commands


def verify_factory(secret: str) -> Callable[[str], bool]:
    """Create a function that verifies time-based one-time passwords."""

    def verify(code: str) -> bool:
        """Return whether the code matches the configured TOTP secret."""
        totp = pyotp.TOTP(secret)
        return totp.verify(code)

    return verify


def _require(ok: bool, message: str) -> bool:
    """Raise a Discord check failure when a permission condition is false."""
    if not ok:
        raise app_commands.CheckFailure(message)
    return True


def is_owner(strict: bool = True):
    """Require the configured bot owner or a user with the owners permission."""

    async def predicate(interaction: discord.Interaction) -> bool:
        """Check the interaction user against the selected owner policy."""
        if strict:
            return _require(
                str(interaction.user.id) == interaction.client.owner,
                "Only the bot owner can use this command.",
            )
        return _require(
            interaction.client.perms_check(interaction, perm="owners"),
            "You need the `owners` permission to use this command.",
        )

    return app_commands.check(predicate)


def privileged_only():
    """Require the privileged permission for a command."""

    async def predicate(interaction: discord.Interaction) -> bool:
        """Check whether the interaction user has the privileged permission."""
        return _require(
            interaction.client.perms_check(interaction, perm="privileged"),
            "You need the `privileged` permission to use this command.",
        )

    return app_commands.check(predicate)


def nxbt_permission():
    """Require the NXBT permission for a command."""

    async def predicate(interaction: discord.Interaction) -> bool:
        """Check whether the interaction user has the NXBT permission."""
        return _require(
            interaction.client.perms_check(interaction, perm="nxbt"),
            "You need the `nxbt` permission to use this command.",
        )

    return app_commands.check(predicate)


def drive_permission():
    """Require the drive permission for a command."""

    async def predicate(interaction: discord.Interaction) -> bool:
        """Check whether the interaction user has the drive permission."""
        return _require(
            interaction.client.perms_check(interaction, perm="drive"),
            "You need the `drive` permission to use this command.",
        )

    return app_commands.check(predicate)


def nonglobal_command():
    """Restrict a command to servers where it is allowed."""

    async def predicate(interaction: discord.Interaction) -> bool:
        """Allow DMs or check the command's server-specific allowance."""
        if interaction.guild is None:
            return True
        return _require(
            interaction.client.perms_check(
                interaction, perm="allowed_commands", command=interaction.command.name
            ),
            f"`/{interaction.command.name}` is not allowed in this server.",
        )

    return app_commands.check(predicate)


def button_requires_role(role_name):
    """Decorate a button callback with a required role-name check."""

    def decorator(func):
        """Wrap a callback with the role check."""

        @functools.wraps(func)
        async def wrapper(
            self, interaction: discord.Interaction, button: discord.ui.Button
        ):
            """Reject users without a required role before calling the callback."""
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
    """Decorate a button callback with required Discord channel permissions."""

    def decorator(func):
        """Wrap a callback with server and permission checks."""

        @functools.wraps(func)
        async def wrapper(
            self, interaction: discord.Interaction, button: discord.ui.Button
        ):
            """Reject invalid or under-permissioned interactions before callback."""
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
