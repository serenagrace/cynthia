import discord
from discord import app_commands
from cynthia.utils.auth import nxbt_permission, privileged_only
from cynthia.utils.nxbt_utils import Macro, Input
from cynthia.utils.onmessage import OnMessage
from cynthia.daemons.dman import daemon_running
import asyncio
import io
import nxbt


@app_commands.command()
@daemon_running("NXBTDaemon")
@privileged_only()
async def connect(interaction: discord.Interaction):
    await interaction.response.defer()
    nxbt_daemon = interaction.client.dman.running_daemons["NXBTDaemon"]
    if nxbt_daemon.connected:
        await interaction.followup.send("Already connected to Nintendo Switch!")
        return

    success = await nxbt_daemon.connect()
    if not success:
        await interaction.followup.send("Connection timed out.")
        return
    await interaction.followup.send("Connected to Nintendo Switch!")


@app_commands.command()
@daemon_running("NXBTDaemon")
@nxbt_permission()
async def disconnect(interaction: discord.Interaction):
    await interaction.response.defer(thinking=False, ephemeral=True)
    nxbt_daemon = interaction.client.dman.running_daemons["NXBTDaemon"]
    if not nxbt_daemon.connected:
        await interaction.followup.send("Disconnected from Nintendo Switch.")
        return

    success = await nxbt_daemon.disconnect()
    if not success:
        await interaction.followup.send("Disconnect Failed.")
        return
    await interaction.followup.send("Disconnected from Nintendo Switch.")


@app_commands.command()
@nxbt_permission()
@daemon_running("NXBTDaemon")
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
    nxbt_daemon = interaction.client.dman.running_daemons["NXBTDaemon"]
    if not nxbt_daemon.connected:
        await interaction.response.send_message(
            "Not connected to Nintendo Switch. Use /connect to connect."
        )
        return
    nxbt_daemon.queue(Macro(Input([getattr(nxbt.Buttons, action.value, None)])))
    nxbt_daemon.unpause()
    await interaction.followup.send("Input received.")


@app_commands.command()
@daemon_running("NXBTDaemon")
@privileged_only()
async def use_channel_as_input(interaction: discord.Interaction):
    await interaction.response.defer(thinking=False, ephemeral=True)
    if interaction.channel_id is None or interaction.guild_id is None:
        await interaction.followup.send(
            "This command can only be used in a guild channel."
        )
        return

    OnMessage.units[f"nxbt_{interaction.guild_id}_{interaction.channel_id}"] = (
        OnMessage(
            _type="nxbt",
            action_type="nxbt",
            channel=interaction.channel,
            guild=interaction.guild,
            persist=False,
        )
    )
    nxbt_daemon = interaction.client.dman.running_daemons["NXBTDaemon"]
    nxbt_daemon.unpause()

    await interaction.followup.send(
        "Now using this channel as input. Send button commands here."
    )


# TODO: make channel/guild optional arguments
@app_commands.command()
@privileged_only()
async def stop_using_channel_as_input(interaction: discord.Interaction):
    await interaction.response.defer(thinking=False, ephemeral=True)
    onmessage_key = f"nxbt_{interaction.guild_id}_{interaction.channel_id}"
    if onmessage_key in OnMessage.units:
        del OnMessage.units[onmessage_key]
    await interaction.followup.send("Stopped accepting channel input.")


@app_commands.context_menu(name="Define Macro")
@nxbt_permission()
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


@app_commands.context_menu(name="Queue Macro")
@nxbt_permission()
@daemon_running("NXBTDaemon")
async def queue_macro_context(
    interaction: discord.Interaction, message: discord.Message
):
    await interaction.response.defer(thinking=False, ephemeral=True)
    nxbt_daemon = interaction.client.dman.running_daemons["NXBTDaemon"]
    content = message.content
    macro = Macro(content)
    if not nxbt_daemon.connected:
        await interaction.followup.send(
            "Not connected to Nintendo Switch. Use /connect to connect."
        )
        return
    nxbt_daemon.queue(macro)
    await interaction.followup.send("Macro Queued.")


@app_commands.command()
@nxbt_permission()
@daemon_running("NXBTDaemon")
async def queue_macro(interaction: discord.Interaction, macro: str):
    await interaction.response.defer(thinking=False, ephemeral=True)
    nxbt_daemon = interaction.client.dman.running_daemons["NXBTDaemon"]
    if not nxbt_daemon.connected:
        await interaction.followup.send(
            "Not connected to Nintendo Switch. Use /connect to connect."
        )
        return
    macro_str = Macro._macro_tree.get(macro.lower(), None)
    if macro_str is None:
        await interaction.followup.send(f"No macro found with name '{macro}'.")
        return
    nxbt_daemon.queue(macro_str)
    await interaction.followup.send(f"Macro '{macro.lower()}' Queued.")


@app_commands.command()
@nxbt_permission()
async def get_macro(interaction: discord.Interaction, macro: str):
    await interaction.response.defer()
    macro_str = Macro._macro_tree.get(macro.lower(), None)
    if macro_str is None:
        await interaction.followup.send(f"No macro found with name '{macro}'.")
        return
    await interaction.followup.send(f"```\n{macro_str}```")


@app_commands.command()
@nxbt_permission()
@daemon_running("CVDaemon")
async def show(interaction: discord.Interaction):
    await interaction.response.defer()

    # Try to get the CVDaemon memory
    def tryload(interaction):
        ns = None
        cv = interaction.client.dman.running_daemons.get("CVDaemon", None)
        if cv is not None:
            ns = getattr(cv, "ns", None)
        return ns

    ns = tryload(interaction)
    async with asyncio.timeout(10):
        while ns is None:
            await asyncio.sleep(0.05)
            ns = tryload(interaction)
    if ns is not None:
        embed, buffer = ns.embed, ns.png
        io_buf = io.BytesIO(buffer)
        io_buf.seek(0)
        png = discord.File(fp=io_buf, filename="frame.png")
        if png is not None:
            await interaction.followup.send(embed=embed, file=png)
            return

    await interaction.followup.send("Failed to read frame from UVC device.")


@app_commands.command()
@nxbt_permission()
@daemon_running("NXBTDaemon")
async def pause(interaction: discord.Interaction):
    nxbt_daemon = interaction.client.dman.running_daemons["NXBTDaemon"]
    nxbt_daemon.pause()
    await interaction.response.send_message("Macro Playback paused.")


@app_commands.command()
@nxbt_permission()
@daemon_running("NXBTDaemon")
async def unpause(interaction: discord.Interaction):
    nxbt_daemon = interaction.client.dman.running_daemons["NXBTDaemon"]
    nxbt_daemon.unpause()
    await interaction.response.send_message("Macro Playback resumed.")


@app_commands.command()
@nxbt_permission()
@daemon_running("NXBTDaemon")
async def loop(interaction: discord.Interaction, value: bool):
    nxbt_daemon = interaction.client.dman.running_daemons["NXBTDaemon"]
    nxbt_daemon.set_loop(loop=value)
    await interaction.response.send_message("Loop Behavior updated.")


@app_commands.command()
@nxbt_permission()
@daemon_running("NXBTDaemon")
async def stop(interaction: discord.Interaction):
    nxbt_daemon = interaction.client.dman.running_daemons["NXBTDaemon"]
    nxbt_daemon.stop()
    await interaction.response.send_message("Macro Playback stopped, queue cleared.")


@app_commands.command()
@nxbt_permission()
@daemon_running("NXBTDaemon")
async def macro_clear(interaction: discord.Interaction):
    await interaction.response.defer()
    nxbt_daemon = interaction.client.dman.running_daemons["NXBTDaemon"]
    success = await nxbt_daemon.clear_queue()
    if success:
        await interaction.followup.send("Macro queue cleared.")
    else:
        await interaction.followup.send("Error clearing queue.")


@get_macro.autocomplete("macro")
@queue_macro.autocomplete("macro")
async def macro_autocomplete(interaction: discord.Interaction, current: str):
    choices = [
        app_commands.Choice(name=macro_name, value=macro_name)
        for macro_name in Macro._macro_tree.keys()
        if current.lower() in macro_name
    ]
    return choices[:10]


@app_commands.command()
@privileged_only()
async def set_hunt(interaction: discord.Interaction, hunt: str):
    await interaction.response.defer()
    interaction.client.args.hunt = hunt
    await interaction.followup.send(f"Hunt set to '{hunt}'.")


@app_commands.command()
@privileged_only()
async def clear_hunt(interaction: discord.Interaction):
    await interaction.response.defer()
    interaction.client.args.hunt = None
    await interaction.followup.send("Hunt cleared.")


__application__ = (
    connect,
    disconnect,
    switch,
    use_channel_as_input,
    stop_using_channel_as_input,
    define_macro,
    get_macro,
    queue_macro,
    queue_macro_context,
    show,
    pause,
    unpause,
    stop,
    loop,
    macro_clear,
    set_hunt,
    clear_hunt,
)
