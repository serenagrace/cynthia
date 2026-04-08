import discord
from discord import app_commands
from cynthia.utils.auth import nxbt_permission, privileged_only
from cynthia.utils.nxbt_utils import CHAR_MAP, MACROS, Macro, Input
from ..onmessage import OnMessage
import asyncio
import nxbt


@app_commands.command()
@privileged_only()
async def connect(interaction: discord.Interaction):

    await interaction.response.defer()

    nx = getattr(interaction.client, "nxbt", None)
    if nx is None:
        nx = nxbt.Nxbt()
        setattr(interaction.client, "nxbt", nx)

    controller = getattr(interaction.client, "nxbt_controller", None)
    if controller is None:
        controller = nx.create_controller(
            nxbt.PRO_CONTROLLER, colour_body=[215, 0, 255]
        )
        setattr(interaction.client, "nxbt_controller", controller)
    else:
        await interaction.followup.send("Already connected to Nintendo Switch!")
        return

    await asyncio.to_thread(nx.wait_for_connection, controller)
    await interaction.followup.send("Connected to Nintendo Switch!")

    await Macro(None, [Input(nxbt.Buttons.A, up_duration=1.0), nxbt.Buttons.B]).play(
        nx, controller
    )

    async def cleanup(client):
        nx = getattr(client, "nxbt", None)
        controller = getattr(client, "nxbt_controller", None)
        await MACROS["cleanup"].play(nx, controller)
        nx.remove_controller(controller)
        client.nxbt = None
        client.nxbt_controller = None

    interaction.client.onexit["nxbt"] = cleanup
    return


@app_commands.command()
@nxbt_permission()
async def disconnect(interaction: discord.Interaction):
    await interaction.response.defer(thinking=False, ephemeral=True)
    nx = getattr(interaction.client, "nxbt", None)
    controller = getattr(interaction.client, "nxbt_controller", None)
    if nx is None or controller is None:
        interaction.followup.send("Done.")
        return

    interaction.client.onexit["nxbt"](interaction.client)
    interaction.client.onexit["nxbt"] = None
    interaction.client = None

    await interaction.followup.send("Disconnected from Nintendo Switch.")


@app_commands.command()
@nxbt_permission()
@app_commands.choices(
    action=[
        app_commands.Choice(name="A", value="A"),
        app_commands.Choice(name="B", value="B"),
        app_commands.Choice(name="X", value="X"),
        app_commands.Choice(name="Y", value="Y"),
        app_commands.Choice(name="L", value="L"),
        app_commands.Choice(name="R", value="R"),
        app_commands.Choice(name="ZL", value="ZL"),
        app_commands.Choice(name="ZR", value="ZR"),
        app_commands.Choice(name="LS", value="L_STICK_PRESS"),
        app_commands.Choice(name="RS", value="R_STICK_PRESS"),
        app_commands.Choice(name="Up", value="DPAD_UP"),
        app_commands.Choice(name="Down", value="DPAD_DOWN"),
        app_commands.Choice(name="Left", value="DPAD_LEFT"),
        app_commands.Choice(name="Right", value="DPAD_RIGHT"),
        app_commands.Choice(name="+", value="PLUS"),
        app_commands.Choice(name="-", value="MINUS"),
        app_commands.Choice(name="Home", value="HOME"),
        app_commands.Choice(name="Capture", value="CAPTURE"),
    ]
)
async def switch(interaction: discord.Interaction, action: app_commands.Choice[str]):
    await interaction.response.defer(thinking=False, ephemeral=True)
    nx = getattr(interaction.client, "nxbt", None)
    controller = getattr(interaction.client, "nxbt_controller", None)
    if nx is None or controller is None:
        await interaction.response.send_message(
            "Not connected to Nintendo Switch. Use /connect to connect."
        )
        return
    await Input([getattr(nxbt.Buttons, action.value, None)], 0.1, 0.5).play(
        nx, controller
    )
    await interaction.followup.send("Input received.")


@app_commands.command()
@privileged_only()
async def use_channel_as_input(interaction: discord.Interaction):
    await interaction.response.defer(thinking=False, ephemeral=True)
    nx = getattr(interaction.client, "nxbt", None)
    controller = getattr(interaction.client, "nxbt_controller", None)
    if nx is None or controller is None:
        await interaction.followup.send(
            "Not connected to Nintendo Switch. Use /connect to connect."
        )
        return

    if interaction.channel_id is None or interaction.guild_id is None:
        await interaction.followup.send(
            "This command can only be used in a guild channel."
        )
        return

    def condition(message: discord.Message):
        return (
            interaction.channel_id == interaction.channel_id
            and message.guild_id == interaction.guild_id
        )

    async def action(client, message):
        nx = getattr(client, "nxbt", None)
        controller = getattr(client, "nxbt_controller", None)

        content = message.content
        macro = Macro(None, message.content)
        await macro.play(nx, controller)

    interaction.client.onmessage["nxbt_input"] = OnMessage(
        interaction.client,
        action=action,
        channel=interaction.channel_id,
        guild=interaction.guild_id,
    )

    await interaction.followup.send(
        "Now using this channel as input. Send button commands here."
    )


@app_commands.command()
@privileged_only()
async def stop_using_channel_as_input(interaction: discord.Interaction):
    await interaction.response.defer(thinking=False, ephemeral=True)
    if "nxbt_input" in interaction.client.onmessage:
        del interaction.client.onmessage["nxbt_input"]
    await interaction.followup.send("Stopped accepting channel input.")


__application__ = (
    connect,
    disconnect,
    switch,
    use_channel_as_input,
    stop_using_channel_as_input,
)
