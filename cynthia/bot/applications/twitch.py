"""Owner-only DM commands that run Twitch streams through OBS."""

import asyncio
import logging

import discord
from discord import app_commands

from cynthia.utils.auth import OwnerGroup
from cynthia.utils.obs import OBSError
from cynthia.utils.obslayout import LayoutError
from cynthia.utils.streamcfg import setting

logger = logging.getLogger(__name__)

TEST_TASK = "_twitch_test_task"

twitch = OwnerGroup(name="twitch", description="Stream to Twitch through OBS.")


def obs_cog(interaction):
    """Return the OBS cog or explain that it isn't loaded."""
    cog = interaction.client.get_cog("OBSCog")
    if cog is None:
        raise app_commands.CheckFailure("The OBS cog isn't loaded.")
    return cog


def stream_key(interaction):
    """The Twitch key from `.env` (`TWITCH_STREAM_KEY`, else `OBS_STREAM_KEY`)."""
    env = interaction.client.env
    return env.get("TWITCH_STREAM_KEY", None) or env.get("OBS_STREAM_KEY", None)


def channel(interaction):
    """The Twitch channel name from `.env`, if set."""
    return interaction.client.env.get("TWITCH_CHANNEL", None) or None


def duration(seconds):
    """Format seconds as `1h 02m 03s`."""
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    return f"{minutes}m {secs:02d}s" if minutes else f"{secs}s"


def summarize(status):
    """One block of health numbers for a running stream."""
    seconds = max(status["stream_seconds"], 1)
    total = max(status["total_frames"], 1)
    return (
        f"Uptime: {duration(status['stream_seconds'])}\n"
        f"Average bitrate: {status['bytes'] * 8 / seconds / 1000:.0f} kbps\n"
        f"Skipped frames: {status['skipped_frames']} "
        f"({status['skipped_frames'] / total:.2%})\n"
        f"Congestion: {status['congestion']:.0%}"
        + ("\nReconnecting…" if status["reconnecting"] else "")
    )


async def begin(interaction, bandwidth_test):
    """Prepare OBS (video mode, layout, key) and start streaming."""
    cog = obs_cog(interaction)
    status = await asyncio.to_thread(cog.obs.status)
    if status["streaming"]:
        raise OBSError("OBS is already streaming; use `/twitch stop` first.")
    uns = interaction.client.dman.uns
    kbps = int(interaction.client.config.get("twitch_bitrate_kbps", 6000))
    await cog.prepare()
    await asyncio.to_thread(
        cog.obs.set_stream_key, stream_key(interaction), bandwidth_test, kbps
    )
    await asyncio.to_thread(cog.obs.start_stream)
    return f"{setting(uns, 'obs_height')}p{setting(uns, 'obs_fps')} at {kbps} kbps"


@twitch.command(name="start", description="Start streaming to Twitch.")
async def start(interaction: discord.Interaction):
    """Start the Twitch stream."""
    await interaction.response.defer(thinking=True)
    try:
        mode = await begin(interaction, bandwidth_test=False)
    except (OBSError, LayoutError) as e:
        await interaction.followup.send(f"❌ {e}")
        return
    url = f"\n{twitch_url(interaction)}" if channel(interaction) else ""
    await interaction.followup.send(f"🔴 Streaming to Twitch, {mode}.{url}")


@twitch.command(
    name="stop", description="Stop the Twitch stream (or a bandwidth test)."
)
async def stop(interaction: discord.Interaction):
    """Stop the Twitch stream."""
    await interaction.response.defer(thinking=True)
    cog = obs_cog(interaction)
    task = getattr(interaction.client, TEST_TASK, None)
    if task is not None and not task.done():
        task.cancel()
    try:
        status = await asyncio.to_thread(cog.obs.status)
        if not status["streaming"]:
            await interaction.followup.send("OBS isn't streaming.")
            return
        await asyncio.to_thread(cog.obs.stop_stream)
    except OBSError as e:
        await interaction.followup.send(f"❌ {e}")
        return
    await interaction.followup.send(f"⏹️ Stream stopped.\n{summarize(status)}")


@twitch.command(name="test", description="Run Twitch's bandwidth test through OBS.")
@app_commands.describe(minutes="How long to test before stopping automatically")
async def test(
    interaction: discord.Interaction, minutes: app_commands.Range[int, 1, 10] = 2
):
    """Stream in Twitch's bandwidth-test mode (nothing goes live), then report."""
    await interaction.response.defer(thinking=True)
    try:
        mode = await begin(interaction, bandwidth_test=True)
    except (OBSError, LayoutError) as e:
        await interaction.followup.send(f"❌ {e}")
        return
    await interaction.followup.send(
        f"📶 Bandwidth test running at {mode}. Nothing goes live. "
        f"I'll stop and report in {minutes} min (or use `/twitch stop`)."
    )
    task = asyncio.create_task(finish_test(interaction, minutes))
    setattr(interaction.client, TEST_TASK, task)


async def finish_test(interaction, minutes):
    """Wait out the test, stop streaming, and DM the numbers."""
    cog = obs_cog(interaction)
    try:
        await asyncio.sleep(minutes * 60)
        status = await asyncio.to_thread(cog.obs.status)
        await asyncio.to_thread(cog.obs.stop_stream)
        message = f"📶 Bandwidth test finished.\n{summarize(status)}"
    except asyncio.CancelledError:
        return
    except OBSError as e:
        message = f"❌ The bandwidth test ended with an error: {e}"
    await interaction.user.send(message)


def twitch_url(interaction):
    """The channel's public URL."""
    return f"https://twitch.tv/{channel(interaction)}"


@twitch.command(name="url", description="Show the Twitch channel URL.")
async def url(interaction: discord.Interaction):
    """Show the channel URL."""
    if not channel(interaction):
        await interaction.response.send_message(
            "Set `TWITCH_CHANNEL` in `.env` first.", ephemeral=True
        )
        return
    await interaction.response.send_message(twitch_url(interaction))


@twitch.command(name="uptime", description="Show how long the stream has been live.")
async def uptime(interaction: discord.Interaction):
    """Show the stream's uptime."""
    await interaction.response.defer(thinking=True)
    try:
        status = await asyncio.to_thread(obs_cog(interaction).obs.status)
    except OBSError as e:
        await interaction.followup.send(f"❌ {e}")
        return
    if not status["streaming"]:
        await interaction.followup.send("OBS isn't streaming.")
        return
    await interaction.followup.send(f"Live for {duration(status['stream_seconds'])}.")


@twitch.command(name="status", description="Show stream health and the video mode.")
async def status(interaction: discord.Interaction):
    """Show OBS output health."""
    await interaction.response.defer(thinking=True)
    try:
        info = await asyncio.to_thread(obs_cog(interaction).obs.status)
    except OBSError as e:
        await interaction.followup.send(f"❌ {e}")
        return
    uns = interaction.client.dman.uns
    mode = f"{setting(uns, 'obs_height')}p{setting(uns, 'obs_fps')}"
    if info["streaming"]:
        text = f"🔴 Live, {mode}\n{summarize(info)}"
    else:
        text = f"Not streaming (OBS set to {mode})."
    if info["recording"]:
        text += f"\n⏺️ Recording for {duration(info['record_seconds'])}."
    await interaction.followup.send(text)


__application__ = twitch
