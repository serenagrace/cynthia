"""Cog that watches OBS, keeps the capture mode informed, and applies the layout."""

import asyncio
import logging
from pathlib import Path

from discord.ext import commands, tasks

from cynthia.utils.obs import OBSControl, OBSError
from cynthia.utils.obslayout import LayoutError, load_layout
from cynthia.utils.streamcfg import setting

logger = logging.getLogger(__name__)

POLL_SECONDS = 2.0


class OBSCog(commands.Cog):
    """Poll OBS output state and expose the controller to commands."""

    def __init__(self, bot):
        """Create the controller from the dotenv values and config."""
        self.bot = bot
        self.obs = OBSControl.from_context(bot.env, bot.config)
        bot.obs = self.obs
        self.was_connected = False
        self.last_status = None

    async def cog_load(self):
        """Start polling OBS."""
        self.poll.start()

    async def cog_unload(self):
        """Stop polling and disconnect from OBS."""
        self.poll.cancel()
        await asyncio.to_thread(self.obs.close)
        self.bot.dman.uns.obs_active = False

    @tasks.loop(seconds=POLL_SECONDS)
    async def poll(self):
        """Mirror whether OBS is streaming or recording into the shared state."""
        uns = self.bot.dman.uns
        try:
            status = await asyncio.to_thread(self.obs.status)
        except OBSError:
            if self.was_connected:
                logger.info("Lost the OBS connection.")
            self.was_connected = False
            self.last_status = None
            uns.obs_active = False
            return
        except Exception:
            logger.exception("OBS poll failed.")
            return
        self.last_status = status
        uns.obs_active = bool(status["streaming"] or status["recording"])
        if not self.was_connected:
            self.was_connected = True
            logger.info("Connected to OBS.")
            if not uns.obs_active:
                try:
                    await self.apply_video()
                except OBSError as e:
                    logger.warning("Couldn't set the OBS video settings: %s", e)
            await self.apply_layout(quiet=True)

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
