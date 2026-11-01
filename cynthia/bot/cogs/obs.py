"""Cog that watches OBS, keeps the capture mode informed, and applies the layout."""

import asyncio
import logging
import time
from pathlib import Path

from discord.ext import commands, tasks

from cynthia.utils.obs import OBSControl, OBSError
from cynthia.utils.obslayout import LayoutError, load_layout
from cynthia.utils.streamcfg import setting

logger = logging.getLogger(__name__)

POLL_SECONDS = 2.0
# Twitch ends broadcasts at 48 hours, so restart well before that
DEFAULT_RESTART_HOURS = 24
# How long to wait for OBS to finish stopping before starting again
STOP_TIMEOUT_SECONDS = 60
# Stop a stream that has shown the capture card's no-signal screen this long
DEFAULT_NO_SIGNAL_STOP_MINUTES = 10
NO_SIGNAL_SCENE = "elgato_no_signal"
NO_SIGNAL_SCORE = 0.9


class OBSCog(commands.Cog):
    """Poll OBS output state and expose the controller to commands."""

    def __init__(self, bot):
        """Create the controller from the dotenv values and config."""
        self.bot = bot
        self.obs = OBSControl.from_context(bot.env, bot.config)
        bot.obs = self.obs
        self.was_connected = False
        self.last_status = None
        self.restart_task = None
        self.no_signal_since = None

    async def cog_load(self):
        """Start polling OBS."""
        self.poll.start()

    async def cog_unload(self):
        """Stop polling and disconnect from OBS."""
        self.poll.cancel()
        if self.restart_task is not None:
            self.restart_task.cancel()
        await asyncio.to_thread(self.obs.close)
        self.set_active(False)

    def set_active(self, active):
        """Share whether OBS is live; False if the daemon manager has shut down."""
        try:
            self.bot.dman.uns.obs_active = active
        except (EOFError, OSError):
            # The manager stops before the cog during restart and shutdown
            return False
        return True

    @tasks.loop(seconds=POLL_SECONDS)
    async def poll(self):
        """Mirror whether OBS is streaming or recording into the shared state."""
        try:
            status = await asyncio.to_thread(self.obs.status)
        except OBSError:
            if self.was_connected:
                logger.info("Lost the OBS connection.")
            self.was_connected = False
            self.last_status = None
            if not self.set_active(False):
                self.poll.cancel()
            return
        except Exception:
            logger.exception("OBS poll failed.")
            return
        self.last_status = status
        active = bool(status["streaming"] or status["recording"])
        if not self.set_active(active):
            self.poll.cancel()
            return
        if self.restart_due(status):
            self.restart_task = asyncio.create_task(self.restart_stream(status))
        if self.no_signal_due(status, time.monotonic()):
            await self.stop_for_no_signal()
        if not self.was_connected:
            self.was_connected = True
            logger.info("Connected to OBS.")
            if not active:
                try:
                    await self.apply_video()
                except OBSError as e:
                    logger.warning("Couldn't set the OBS video settings: %s", e)
            await self.apply_layout(quiet=True)

    def restart_due(self, status):
        """Whether a long stream should be restarted before Twitch cuts it off."""
        if self.restart_task is not None and not self.restart_task.done():
            return False
        hours = float(
            self.bot.config.get("twitch_restart_hours", DEFAULT_RESTART_HOURS)
        )
        return (
            hours > 0
            and status["streaming"]
            and status["stream_seconds"] >= hours * 3600
        )

    async def restart_stream(self, status):
        """Stop the stream, wait for OBS to finish, and start it again."""
        hours = status["stream_seconds"] / 3600
        logger.info("Restarting the stream after %.1f hours.", hours)
        try:
            await asyncio.to_thread(self.obs.stop_stream)
            deadline = time.monotonic() + STOP_TIMEOUT_SECONDS
            while (await asyncio.to_thread(self.obs.status))["streaming"]:
                if time.monotonic() > deadline:
                    raise OBSError("OBS didn't stop the stream in time.")
                await asyncio.sleep(POLL_SECONDS)
            await asyncio.to_thread(self.obs.start_stream)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Couldn't restart the stream.")
            await self.tell_owner(
                f"❌ Couldn't restart the stream after {hours:.0f} hours: {e}",
                alert=True,
            )
            return
        logger.info("Restarted the stream.")
        await self.tell_owner(
            f"🔁 Restarted the stream after {hours:.0f} hours "
            "(Twitch ends streams at 48)."
        )

    def no_signal(self):
        """Whether CV's best scene match is the capture card's no-signal screen."""
        try:
            scores = list(getattr(self.bot.dman.uns, "ssim_scores", None) or [])
        except (EOFError, OSError):
            return False
        if not scores:
            return False
        scene, score = scores[0]
        return scene == NO_SIGNAL_SCENE and score > NO_SIGNAL_SCORE

    def no_signal_due(self, status, now):
        """Whether the stream has shown no signal for too long."""
        minutes = float(
            self.bot.config.get(
                "twitch_no_signal_stop_minutes", DEFAULT_NO_SIGNAL_STOP_MINUTES
            )
        )
        if minutes <= 0 or not status["streaming"] or not self.no_signal():
            self.no_signal_since = None
            return False
        if self.restart_task is not None and not self.restart_task.done():
            return False
        if self.no_signal_since is None:
            self.no_signal_since = now
        return now - self.no_signal_since >= minutes * 60

    async def stop_for_no_signal(self):
        """End the stream after a long no-signal stretch and tell the owner."""
        minutes = (time.monotonic() - self.no_signal_since) / 60
        self.no_signal_since = None
        logger.warning(
            "Stopping the stream: no capture signal for %.0f minutes.", minutes
        )
        try:
            await asyncio.to_thread(self.obs.stop_stream)
        except OBSError as e:
            logger.warning("Couldn't stop the stream: %s", e)
            await self.tell_owner(
                f"❌ No capture signal for {minutes:.0f} minutes, "
                f"but stopping the stream failed: {e}",
                alert=True,
            )
            return
        await self.tell_owner(
            f"⏹️ Stopped the stream: no capture signal for {minutes:.0f} minutes.",
            alert=True,
        )

    async def tell_owner(self, text, alert=False):
        """DM the owner, without letting a Discord error break the restart."""
        try:
            await self.bot.messenger.msg_owner(text, alert=alert)
        except Exception:
            logger.exception("Couldn't message the owner.")

    @poll.before_loop
    async def before_poll(self):
        """Wait for the bot to be ready before the first poll."""
        await self.bot.wait_until_ready()

    def layout_path(self):
        """Where the layout file lives (relative paths are from the working dir)."""
        return Path(str(self.bot.config.get("obs_layout_file", "obs_layout.yaml")))

    async def apply_layout(self, quiet=False):
        """Rebuild the OBS scene from the layout file; returns the pane count."""
        try:
            panes = await asyncio.to_thread(load_layout, self.layout_path())
            count = await asyncio.to_thread(
                self.obs.apply_layout,
                panes,
                8000,
                int(self.bot.config.get("obs_feed_port", 5000)),
            )
        except (LayoutError, OBSError) as e:
            if not quiet:
                raise
            logger.warning("Couldn't apply the OBS layout: %s", e)
            return None
        logger.info("Applied the OBS layout (%s panes).", count)
        return count

    async def apply_video(self):
        """Push the configured OBS resolution and frame rate into OBS."""
        uns = self.bot.dman.uns
        await asyncio.to_thread(
            self.obs.set_video, setting(uns, "obs_height"), setting(uns, "obs_fps")
        )

    async def prepare(self):
        """Match OBS's canvas and layout to the OBS settings before an output starts."""
        await self.apply_video()
        await self.apply_layout()


async def setup(bot):
    """Register the OBS cog with the bot."""
    await bot.add_cog(OBSCog(bot))
