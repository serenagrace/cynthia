import discord
from discord import app_commands
from cynthia.utils.auth import nxbt_permission, privileged_only
from cynthia.utils.nxbt_utils import CHAR_MAP, MACROS, Macro, Input
from cynthia.utils.onmessage import OnMessage, ONMESSAGE
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

    try:
        await asyncio.wait_for(
            asyncio.to_thread(nx.wait_for_connection, controller), timeout=30
        )
    except TimeoutError:
        await interaction.followup.send("Connection timed out.")
        nx.remove_controller(controller)
        interaction.client.nxbt_controller = None
        return
    await interaction.followup.send("Connected to Nintendo Switch!")

    await Macro(
        [Input(nxbt.Buttons.A, up_duration=1.0), nxbt.Buttons.B, nxbt.Buttons.HOME]
    ).play(nx, controller)

    async def cleanup(client):
        print("Nxbt cleanup")
        nx = getattr(client, "nxbt", None)
        controller = getattr(client, "nxbt_controller", None)
        if nx is None or controller is None:
            print("Skipping nxbt cleanup due to no controller")
            return
            self.action = action
        try:
            print("Playing cleanup macro")
            await asyncio.wait_for(MACROS["cleanup"].play(nx, controller), timeout=15)
        except TimeoutError:
            print("Cleanup macro timed out.")
        await asyncio.sleep(1)
        try:
            await asyncio.wait_for(
                asyncio.to_thread(nx.remove_controller, controller), timeout=10
            )
        except TimeoutError:
            print("Removing controller timed out.")
        print("Controller removed")
        client.nxbt_controller = None
        client.nxbt = None

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

    cleanup = getattr(interaction.client.onexit, "nxbt", None)
    if cleanup is not None:
        await interaction.client.onexit["nxbt"](interaction.client)
    print("Setting onexit None")
    interaction.client.onexit["nxbt"] = None
    print("delling onexit")
    del interaction.client.onexit["nxbt"]

    controller = getattr(interaction.client, "nxbt_controller", None)
    if controller is not None:
        nx.remove_controller(controller)
        del interaction.client.nxbt_controller

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

    async def action(client, message):
        nx = getattr(client, "nxbt", None)
        controller = getattr(client, "nxbt_controller", None)

        if nx is None or controller is None:
            return

        macro = Macro(message.content)
        await macro.play(nx, controller)

    ONMESSAGE["nxbt_input"] = OnMessage(
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
    if "nxbt_input" in ONMESSAGE:
        del ONMESSAGE["nxbt_input"]
    await interaction.followup.send("Stopped accepting channel input.")


@app_commands.command()
@privileged_only()
async def redefine(interaction: discord.Interaction, name: str):
    await interaction.response.defer(thinking=False, ephemeral=True)
    macro = MACROS.get(name.lower(), None)
    if macro is None:
        await interaction.followup.send(f"No macro found with name '{name}'.")
        return
    macro.redefine()
    await interaction.followup.send(f"Macro '{name}' redefined.")


@app_commands.context_menu(name="Define Macro")
@privileged_only()
async def define_macro(interaction: discord.Interaction, message: discord.Message):
    await interaction.response.defer(thinking=False, ephemeral=True)
    content = message.content
    macro = Macro(content, force=True)
    if macro.name is None:
        await interaction.followup.send(
            "No macro name detected. Please include a name in the macro definition."
        )
        return
    await interaction.followup.send(f"Macro '{macro.name}' defined.")


@app_commands.command()
@privileged_only()
async def get_macro(interaction: discord.Interaction, macro: str):
    await interaction.response.defer()
    macro_obj = MACROS.get(macro.lower(), None)
    if macro_obj is None:
        await interaction.followup.send(f"No macro found with name '{macro}'.")
        return
    macro_str = macro_obj.get()
    if macro_str is None:
        await interaction.followup.send(
            f"Macro '{macro}' has no original string representation."
        )
        return
    await interaction.followup.send(f"```{macro_str}```")


__application__ = (
    connect,
    disconnect,
    switch,
    use_channel_as_input,
    stop_using_channel_as_input,
    redefine,
    define_macro,
    get_macro,
)
