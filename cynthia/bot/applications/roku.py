import discord
from discord import app_commands
from cynthia.utils.auth import privileged_only
from roku import Roku


@app_commands.command()
@privileged_only()
async def remote(interaction: discord.Interaction):
    def RokuRemoteView(roku: Roku) -> discord.ui.View:
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
                async def callback(interaction: discord.Interaction):
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

    """Control your Roku device remotely."""
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
