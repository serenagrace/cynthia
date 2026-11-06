"""Cog that sets the Twitch title and category from the detected game and hunt."""

import asyncio
import json
import logging
import time

import aiohttp
from discord.ext import commands, tasks

from cynthia.daemons.cv import GAME_TITLES
from cynthia.utils.obslayout import overlay_delay_ms
from cynthia.utils.twitchapi import TwitchAPI, TwitchAPIError, TwitchAuthError

logger = logging.getLogger(__name__)

CHECK_SECONDS = 5.0
# Wait this long after a failed update before trying again
RETRY_SECONDS = 300
STATE_FILE = "twitch_channel.json"
# Seconds to wait, on top of the input visualizer's delay, after a shiny before
# clipping, so the moment has reached Twitch; Twitch clips the 30 s before the call
DEFAULT_CLIP_DELAY_SECONDS = 10
KNOWN_GAMES = frozenset(GAME_TITLES.values())


def hunt_title(hunt, self_encounter=False):
    """The stream title for a hunt, matching the bot's activity text."""
    verb = "Looking for" if self_encounter else "Hunting"
    return f"{verb} shiny {hunt.title()}"


class ChannelInfoTracker:
    """Decide when a detected game or hunt is new enough to change the channel.

    A detection only counts once the same game and hunt have held for
    `confirm_seconds` while a known game is playing. The channel is then
    changed only if the game differs from the last one applied, or a hunt is
    set that differs from the last hunt applied. Anything else, including
    edits made on Twitch, is left alone.
    """

    def __init__(self, confirm_seconds, applied=None):
        """Start from the last applied `{"game", "hunt"}`, if any."""
        self.confirm_seconds = confirm_seconds
        self.applied = dict(applied or {"game": None, "hunt": None})
        self.candidate = None
        self.since = None

    def observe(self, game, hunt, now):
        """Return the `{"game", "hunt"}` to apply, or None to leave the channel."""
        if game is None:
            self.candidate = self.since = None
            return None
        key = (game, hunt)
        if key != self.candidate:
            self.candidate, self.since = key, now
            return None
        if now - self.since < self.confirm_seconds:
            return None
        if game != self.applied.get("game"):
            return {"game": game, "hunt": hunt}
        if hunt is not None and hunt != self.applied.get("hunt"):
            return {"game": game, "hunt": hunt}
        return None

    def mark_applied(self, change):
        """Remember a change that reached Twitch."""
        self.applied = dict(change)


class TwitchInfoCog(commands.Cog):
    """Keep the Twitch channel's title and category in step with the hunt."""

    def __init__(self, bot):
        """Load the Twitch client and the last applied game and hunt."""
        self.bot = bot
        self.api = TwitchAPI.from_env(bot.env, bot.drive)
        bot.twitch_api = self.api
        bot.twitch_chat_api = TwitchAPI.from_env(bot.env, bot.drive, chat=True)
        self.tracker = ChannelInfoTracker(
            float(bot.config.get("twitch_info_confirm_seconds", 60)),
            self._load_state(),
        )
        self.retry_at = 0.0
        self.warned_auth = False
        # None until the first look, so a shiny already pending at startup isn't clipped
        self.shiny_seen = None
        self.clip_task = None

    async def cog_load(self):
        """Start watching the detected game."""
        self.check.start()

    async def cog_unload(self):
        """Stop watching."""
        self.check.cancel()
        if self.clip_task is not None:
            self.clip_task.cancel()

    def _load_state(self):
        """Read the last applied game and hunt from the drive."""
        if not self.bot.drive.exists(STATE_FILE, is_file=True):
            return None
        try:
            with self.bot.drive.open(STATE_FILE, "r") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    def _save_state(self):
        """Write the last applied game and hunt to the drive."""
        if self.bot.drive.enabled:
            with self.bot.drive.open(STATE_FILE, "w") as f:
                json.dump(self.tracker.applied, f)

    def detected(self):
        """Return `(game, hunt, self_encounter)` while a known game is playing."""
        cv = self.bot.dman.running_daemons.get("CVDaemon", None)
        ns = getattr(cv, "ns", None)
        if ns is None:
            return None, None, False
        try:
            playing, home = ns.playing, ns.home
            game, self_encounter = ns.game, bool(ns.self_encounter)
        except (AttributeError, EOFError, OSError):
            return None, None, False
        if not playing or home or game not in KNOWN_GAMES:
            return None, None, False
        return game, self.bot.args.hunt or None, self_encounter

    async def category_id(self, game):
        """Find the Twitch category for a game, honoring `twitch_categories`."""
        override = (self.bot.config.get("twitch_categories", None) or {}).get(game)
        if override and str(override).isdigit():
            return str(override)
        return await self.api.find_category(str(override or game))

    async def apply(self, change, self_encounter):
        """Send the category (and hunt title, if any) to Twitch."""
        game_id = await self.category_id(change["game"])
        if game_id is None:
            logger.warning(
                "No Twitch category is named exactly `%s`; leaving the category. "
                "Map it in `twitch_categories` to set it.",
                change["game"],
            )
        title = hunt_title(change["hunt"], self_encounter) if change["hunt"] else None
        await self.api.update_channel(game_id, title)
        self.tracker.mark_applied(change)
        self._save_state()
        logger.info(
            "Twitch channel set: category `%s`%s",
            change["game"] if game_id else "unchanged",
            f", title `{title}`" if title else "",
        )

    @tasks.loop(seconds=CHECK_SECONDS)
    async def check(self):
        """Clip new shinies and apply a confirmed new game or hunt to the channel."""
        self.watch_shiny()
        if self.api is None or not self.bot.config.get("twitch_auto_info", True):
            return
        game, hunt, self_encounter = self.detected()
        now = time.monotonic()
        change = self.tracker.observe(game, hunt, now)
        if change is None or now < self.retry_at:
            return
        try:
            await self.apply(change, self_encounter)
        except TwitchAuthError as e:
            self.retry_at = now + RETRY_SECONDS
            if not self.warned_auth:
                self.warned_auth = True
                logger.warning("Not updating the Twitch channel: %s", e)
        except (TwitchAPIError, aiohttp.ClientError, asyncio.TimeoutError) as e:
            self.retry_at = now + RETRY_SECONDS
            logger.warning("Couldn't update the Twitch channel: %s", e)
        except Exception:
            self.retry_at = now + RETRY_SECONDS
            logger.exception("Twitch channel update failed.")

    def watch_shiny(self):
        """Start a clip when the hunt stops for a possible shiny."""
        try:
            shiny = bool(getattr(self.bot.dman.uns, "nxbt_daemon_stop", False))
        except (EOFError, OSError):
            return
        new = shiny and self.shiny_seen is False
        self.shiny_seen = shiny
        if not new or self.api is None:
            return
        if not self.bot.config.get("twitch_auto_clip", True):
            return
        if self.clip_task is not None and not self.clip_task.done():
            return
        self.clip_task = asyncio.create_task(self.clip_shiny(self.bot.args.hunt))

    async def stream_live(self):
        """Whether OBS is streaming right now (False without OBS)."""
        obs = getattr(self.bot, "obs", None)
        if obs is None:
            return False
        try:
            return bool((await asyncio.to_thread(obs.status))["streaming"])
        except Exception:
            return False

    def clip_delay(self):
        """Seconds from a shiny to its clip: the input visualizer's delay plus a margin."""
        config = self.bot.config
        overlay_ms = float(config.get("obs_feed_delay_ms", 0)) + float(
            config.get("obs_overlay_lag_ms", 0)
        )
        overlay_ms = overlay_delay_ms(self.bot.dman.uns, overlay_ms)
        margin = float(
            config.get("twitch_clip_delay_seconds", DEFAULT_CLIP_DELAY_SECONDS)
        )
        return max(0.0, overlay_ms / 1000 + margin)

    async def clip_shiny(self, hunt):
        """Clip the shiny once it has reached the stream, and DM the owner the link."""
        await asyncio.sleep(self.clip_delay())
        if not await self.stream_live():
            logger.info("Not clipping the shiny: the stream isn't live.")
            return
        title = f"Shiny {hunt.title()}!" if hunt else "Shiny found!"
        try:
            clip = await self.api.create_clip(title=title)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Couldn't clip the shiny: %s", e)
            await self.tell_owner(f"❌ Couldn't clip the shiny: {e}")
            return
        logger.info("Clipped the shiny: %s", clip.get("edit_url"))
        await self.tell_owner(f"🎬 Clipped the shiny: {clip.get('edit_url')}")

    async def tell_owner(self, text):
        """DM the owner, without letting a Discord error escape."""
        try:
            await self.bot.messenger.msg_owner(text)
        except Exception:
            logger.exception("Couldn't message the owner.")

    @check.before_loop
    async def before_check(self):
        """Wait for the bot to be ready."""
        await self.bot.wait_until_ready()


async def setup(bot):
    """Register the Twitch channel-info cog."""
    await bot.add_cog(TwitchInfoCog(bot))
