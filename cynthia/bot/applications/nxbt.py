import discord
from discord import app_commands
from cynthia.utils.auth import nxbt_permission, privileged_only
from ..onmessage import OnMessage
import asyncio
import nxbt

CHAR_MAP = {
        "a": nxbt.Buttons.A,
        "b": nxbt.Buttons.B,
        "x": nxbt.Buttons.X,
        "y": nxbt.Buttons.Y,
        "l": nxbt.Buttons.L,
        "r": nxbt.Buttons.R,
        "zl": nxbt.Buttons.ZL,
        "zr": nxbt.Buttons.ZR,
        "ls": nxbt.Buttons.L_STICK_PRESS,
        "rs": nxbt.Buttons.R_STICK_PRESS,
        "^": nxbt.Buttons.DPAD_UP,
        "v": nxbt.Buttons.DPAD_DOWN,
        "<": nxbt.Buttons.DPAD_LEFT,
        ">": nxbt.Buttons.DPAD_RIGHT,
        "+": nxbt.Buttons.PLUS,
        "-": nxbt.Buttons.MINUS,
        "h": nxbt.Buttons.HOME,
        "c": nxbt.Buttons.CAPTURE,
        "lsl": nxbt.Buttons.JCL_SL,
        "lsr": nxbt.Buttons.JCL_SR,
        "rsl": nxbt.Buttons.JCR_SL,
        "rsr": nxbt.Buttons.JCR_SR
        }

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
        controller = nx.create_controller(nxbt.PRO_CONTROLLER, colour_body=[215,0,255])
        setattr(interaction.client, "nxbt_controller", controller)
    else:
        await interaction.followup.send("Already connected to Nintendo Switch!")
        return

    await asyncio.to_thread(nx.wait_for_connection, controller)
    await interaction.followup.send("Connected to Nintendo Switch!")

    nx.press_buttons(controller, [nxbt.Buttons.A], down=0.2, up=0.5)
    nx.press_buttons(controller, [nxbt.Buttons.B], down=0.1, up=0.5)

    def cleanup(client):
        nx = getattr(client, "nxbt", None)
        controller = getattr(client, "nxbt_controller", None)
        if nx is not None and controller is not None:
            nx.press_buttons(controller, [nxbt.Buttons.HOME], down=0.1, up=1.0)
            nx.press_buttons(controller, [nxbt.Buttons.DPAD_DOWN], down=0.1, up=0.5)
            for _ in range(6):
                nx.press_buttons(controller, [nxbt.Buttons.DPAD_RIGHT], down=0.1, up=0.5)
            nx.press_buttons(controller, [nxbt.Buttons.A], down=0.1, up=1.5)
            nx.press_buttons(controller, [nxbt.Buttons.A], down=0.1, up=0.5)

    interaction.client.onexit.append(cleanup)


@app_commands.command()
@nxbt_permission()
@app_commands.choices(action=[
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
    app_commands.Choice(name="Capture", value="CAPTURE")
])
async def switch(interaction: discord.Interaction, action: app_commands.Choice[str]):
    await interaction.response.defer(thinking=False, ephemeral=True)
    nx = getattr(interaction.client, "nxbt", None)
    controller = getattr(interaction.client, "nxbt_controller", None)
    if nx is None or controller is None:
        await interaction.response.send_message("Not connected to Nintendo Switch. Use /connect to connect.")
        return
    nx.press_buttons(controller, [getattr(nxbt.Buttons, action.value, None)], down=0.1, up=0.5)
    await interaction.followup.send("Input received.")


@app_commands.command()
@privileged_only()
async def use_channel_as_input(interaction: discord.Interaction):
    await interaction.response.defer(thinking=False, ephemeral=True)
    nx = getattr(interaction.client, "nxbt", None)
    controller = getattr(interaction.client, "nxbt_controller", None)
    if nx is None or controller is None:
        await interaction.response.send_message("Not connected to Nintendo Switch. Use /connect to connect.")
        return

    if interaction.channel_id is None or interaction.guild_id is None:
        await interaction.followup.send("This command can only be used in a guild channel.")
        return

    def condition(message: discord.Message):
        return message.channel_id == interaction.channel_id and message.guild_id == interaction.guild_id

    async def action(message):
        nx = getattr(interaction.client, "nxbt", None)
        controller = getattr(interaction.client, "nxbt_controller", None)
        duration = 0.15

        if not nx or not controller:
            return

        content = message.content.strip().lower()
        inputs = []

        if content.startswith("hold"):
            duration = 1.0

        for char in sorted(CHAR_MAP.keys(), key=lambda x: -len(x)):
            if char in content:
                content = content.replace(char, '')
                inputs.append(CHAR_MAP[char])
        nx.press_buttons(controller, inputs, down=duration, up=0.5)

    interaction.client.onmessage["nxbt_input"] = OnMessage(interaction.client, action=action, channel=interaction.channel_id, guild=interaction.guild_id)

    await interaction.followup.send("Now using this channel as input. Send button commands here.")


@app_commands.command()
@privileged_only()
async def stop_using_channel_as_input(interaction: discord.Interaction):
    await interaction.response.defer(thinking=False, ephemeral=True)
    if "nxbt_input" in interaction.client.onmessage:
        del interaction.client.onmessage["nxbt_input"]
    await interaction.followup.send("Stopped accepting channel input.")


__application__ = connect, switch, use_channel_as_input, stop_using_channel_as_input

