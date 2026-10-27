"""Owner command for controlling the configured Roku device."""

import discord
from discord import app_commands
from roku import Roku

from cynthia.utils.auth import is_owner


@app_commands.command()
@app_commands.default_permissions(administrator=True)
@is_owner()
async def remote(interaction: discord.Interaction):
    """Open an interactive remote for the configured Roku device."""

    def RokuRemoteView(roku: Roku) -> discord.ui.View:
        """Build a button view that sends remote commands to a Roku."""
        view = discord.ui.View(timeout=None)
        buttons = [
            ("Up", "up"),
            ("Down", "down"),
            ("Left", "left"),
            ("Right", "right"),
            ("Select", "select"),
            ("Home", "home"),
            ("Back", "back"),
            ("Volume Up", "volume_up"),
            ("Volume Down", "volume_down"),
            ("Power On", "poweron"),
            ("Power Off", "poweroff"),
        ]
        for label, command in buttons:

            def callback_factory(command):
                """Create a button callback for one Roku command."""

                async def callback(interaction: discord.Interaction):
                    """Send the Roku command and update its power indicator."""
                    getattr(roku, command)()
                    if roku.power_state == "Off":
                        await interaction.message.remove_reaction(
                            "🟢", interaction.client.user
                        )
                        await message.add_reaction("🔴")
                    else:
                        await interaction.message.remove_reaction(
                            "🔴", interaction.client.user
                        )
                        await interaction.message.add_reaction("🟢")
                    await interaction.response.edit_message()

                return callback

            button = discord.ui.Button(label=label)
            button.callback = callback_factory(command)
            view.add_item(button)
        return view

    roku = Roku(interaction.client.config.roku_ip)
    roku.poweron()
    await interaction.response.send_message(
        "Use the buttons below to control your Roku device.",
        view=RokuRemoteView(roku),
    )
    message = await interaction.original_response()
    if roku.power_state == "Off":
        await message.add_reaction("🔴")
    else:
        await message.add_reaction("🟢")


__application__ = remote
