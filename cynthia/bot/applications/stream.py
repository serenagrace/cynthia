"""Owner commands for the web stream and OBS: frame rate, resolution, recording, show."""

import asyncio
import io
from typing import Optional

import discord
from discord import app_commands

from cynthia.utils.auth import OwnerGroup
from cynthia.utils.obs import OBSError
from cynthia.utils.obslayout import LayoutError
from cynthia.utils.streamcfg import (
    CV_FPS,
    FPS_CHOICES,
    RESOLUTIONS,
    capture_mode,
    fps_names,
    height_names,
    setting,
)

FPS_OPTIONS = [app_commands.Choice(name=f"{f} fps", value=f) for f in FPS_CHOICES]
HEIGHT_OPTIONS = [app_commands.Choice(name=f"{h}p", value=h) for h in RESOLUTIONS]

webstream = OwnerGroup(
    name="webstream", description="Frame rate and resolution of the web stream."
)
obs = OwnerGroup(
    name="obs", description="Control OBS: its video mode, recording, layout."
)


def obs_cog(interaction):
    """Return the OBS cog or explain that it isn't loaded."""
    cog = interaction.client.get_cog("OBSCog")
    if cog is None:
        raise app_commands.CheckFailure("The OBS cog isn't loaded.")
    return cog


def capture_note(interaction):
    """Describe the capture mode the running endpoints currently require."""
    height, fps = capture_mode(interaction.client.dman.uns)
    return f"Capture card: {height}p{fps} (CV stays at {CV_FPS} fps)."


def store(interaction, key, value):
    """Apply a stream setting live and persist it in the config."""
    setattr(interaction.client.dman.uns, key, value)
    interaction.client.config.set(key, value)


async def change(interaction, key, value, label, names):
    """Report the current value when none was given; True when one was."""
    if value is None:
        uns = interaction.client.dman.uns
        await interaction.response.send_message(
            f"{label} is `{setting(uns, key)}`. Options: {names}.", ephemeral=True
        )
        return False
    return True


@webstream.command(
    name="framerate", description="Show or set the web stream frame rate."
)
@app_commands.describe(fps=f"Frames per second ({fps_names()})")
@app_commands.choices(fps=FPS_OPTIONS)
async def web_framerate(interaction: discord.Interaction, fps: Optional[int] = None):
    """Show or set the web stream frame rate."""
    if await change(interaction, "web_fps", fps, "Web frame rate", fps_names()):
        store(interaction, "web_fps", fps)
        await interaction.response.send_message(
            f"Web stream is now {fps} fps. {capture_note(interaction)}"
        )


@webstream.command(
    name="resolution", description="Show or set the web stream resolution."
)
@app_commands.describe(height=f"Height ({height_names()})")
@app_commands.choices(height=HEIGHT_OPTIONS)
async def web_resolution(
    interaction: discord.Interaction, height: Optional[int] = None
):
    """Show or set the web stream resolution."""
    if await change(
        interaction, "web_height", height, "Web resolution", height_names()
    ):
        store(interaction, "web_height", height)
        await interaction.response.send_message(
            f"Web stream is now {height}p. {capture_note(interaction)}"
        )


async def change_obs_video(interaction, key, value):
    """Store an OBS video setting and push it into OBS when it is idle."""
    uns = interaction.client.dman.uns
    if getattr(uns, "obs_active", False):
        await interaction.response.send_message(
            "OBS is streaming or recording; stop it before changing its video mode.",
            ephemeral=True,
        )
        return
    await interaction.response.defer(thinking=True)
    store(interaction, key, value)
    try:
        await obs_cog(interaction).prepare()
        applied = "Applied to OBS."
    except (OBSError, LayoutError) as e:
        applied = f"Saved, but OBS wasn't updated: {e}"
    await interaction.followup.send(
        f"OBS is now {setting(uns, 'obs_height')}p{setting(uns, 'obs_fps')}. "
        f"{applied} {capture_note(interaction)}"
    )


@obs.command(name="framerate", description="Show or set the OBS frame rate.")
@app_commands.describe(fps=f"Frames per second ({fps_names()})")
@app_commands.choices(fps=FPS_OPTIONS)
async def obs_framerate(interaction: discord.Interaction, fps: Optional[int] = None):
    """Show or set the OBS frame rate."""
    if await change(interaction, "obs_fps", fps, "OBS frame rate", fps_names()):
        await change_obs_video(interaction, "obs_fps", fps)


@obs.command(name="resolution", description="Show or set the OBS resolution.")
@app_commands.describe(height=f"Height ({height_names()})")
@app_commands.choices(height=HEIGHT_OPTIONS)
async def obs_resolution(
    interaction: discord.Interaction, height: Optional[int] = None
):
    """Show or set the OBS resolution."""
    if await change(
        interaction, "obs_height", height, "OBS resolution", height_names()
    ):
        await change_obs_video(interaction, "obs_height", height)


@obs.command(name="record", description="Start recording in OBS.")
async def obs_record(interaction: discord.Interaction):
    """Prepare OBS's video mode and layout, then start recording."""
    await interaction.response.defer(thinking=True)
    cog = obs_cog(interaction)
    try:
        status = await asyncio.to_thread(cog.obs.status)
        if status["recording"]:
            await interaction.followup.send("OBS is already recording.")
            return
        if not status["streaming"]:
            await cog.prepare()
        await asyncio.to_thread(cog.obs.start_record)
    except (OBSError, LayoutError) as e:
        await interaction.followup.send(f"❌ {e}")
        return
    uns = interaction.client.dman.uns
    await interaction.followup.send(
        f"🔴 Recording at {setting(uns, 'obs_height')}p{setting(uns, 'obs_fps')}."
    )


@obs.command(name="stop", description="Stop recording in OBS.")
async def obs_stop(interaction: discord.Interaction):
    """Stop the OBS recording."""
    await interaction.response.defer(thinking=True)
    cog = obs_cog(interaction)
    try:
        path = await asyncio.to_thread(cog.obs.stop_record)
    except OBSError as e:
        await interaction.followup.send(f"❌ {e}")
        return
    await interaction.followup.send(
        "⏹️ Recording stopped." + (f" Saved to `{path}`." if path else "")
    )


@obs.command(name="layout", description="Rebuild the OBS scene from the layout file.")
async def obs_layout(interaction: discord.Interaction):
    """Re-apply the pane layout to OBS."""
    await interaction.response.defer(thinking=True)
    try:
        count = await obs_cog(interaction).apply_layout()
    except (OBSError, LayoutError) as e:
        await interaction.followup.send(f"❌ {e}")
        return
    await interaction.followup.send(f"Applied the layout: {count} panes.")


@obs.command(name="show", description="Show the current OBS scene.")
async def obs_show(interaction: discord.Interaction):
    """Send a screenshot of what OBS is currently showing."""
    await interaction.response.defer(thinking=True)
    try:
        png = await asyncio.to_thread(obs_cog(interaction).obs.screenshot)
    except OBSError as e:
        await interaction.followup.send(f"❌ {e}")
        return
    await interaction.followup.send(file=discord.File(io.BytesIO(png), "obs.png"))


__application__ = [webstream, obs]
