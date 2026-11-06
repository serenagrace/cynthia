"""Gather a snapshot of the bot, stream, game and controller for the chat model."""

import asyncio
import logging
import time

from cynthia.utils.encounters import (
    average_interval_ms,
    encounter_log_name,
    parse_encounter_log,
)

from .game import ago, describe, duration

logger = logging.getLogger(__name__)

# Twitch's view count changes slowly; don't ask more often than this
TWITCH_REFRESH_SECONDS = 60
PROXY_ERRORS = (AttributeError, EOFError, OSError, BrokenPipeError, ConnectionError)


def read(obj, name, default=None):
    """Read a shared-namespace attribute, tolerating a dead manager proxy."""
    try:
        return getattr(obj, name, default)
    except PROXY_ERRORS:
        return default


def empty_state(now=None):
    """A snapshot with every field present and nothing known."""
    return {
        "now": now or time.time(),
        "bot": {"uptime": 0, "status": None},
        "stream": {
            "live": None,
            "seconds": None,
            "recording": False,
            "viewers": None,
            "title": None,
            "category": None,
        },
        "game": {"title": None, "screen": "unknown", "scene": None},
        "hunt": {
            "target": None,
            "self_encounter": False,
            "encounters": 0,
            "hunting_seconds": None,
            "average_seconds": None,
            "last_encounter": None,
            "stopped": False,
            "shiny_pending": False,
        },
        "controller": {
            "connected": None,
            "running": False,
            "paused": False,
            "looping": False,
        },
        "events": {
            "watchdog_at": None,
            "watchdog_count": 0,
            "failsafe_at": None,
            "failsafe_count": 0,
            "encounter_at": None,
        },
    }


class StateReader:
    """Read live state from the bot's daemons, OBS and Twitch."""

    def __init__(self, bot):
        """Remember the bot; Twitch details are cached between calls."""
        self.bot = bot
        self.twitch = {"at": 0.0, "stream": None}

    def daemon_ns(self, name):
        """The shared namespace of a running daemon, or None."""
        daemon = self.bot.dman.running_daemons.get(name, None)
        return read(daemon, "ns")

    async def snapshot(self):
        """Return the current state; parts that can't be read stay unknown."""
        state = empty_state()
        state["bot"]["uptime"] = time.time() - self.bot.started_at_ms / 1000
        state["bot"]["status"] = read(read(self.bot.vars, "status"), "text")
        for part in (self.read_game, self.read_controller, self.read_events):
            try:
                part(state)
            except Exception:
                logger.debug("Couldn't read %s.", part.__name__, exc_info=True)
        for part in (self.read_hunt, self.read_stream):
            try:
                await part(state)
            except Exception:
                logger.debug("Couldn't read %s.", part.__name__, exc_info=True)
        return state

    def read_game(self, state):
        """The detected game, the screen and the strongest scene."""
        ns = self.daemon_ns("CVDaemon")
        uns = self.bot.dman.uns
        scores = read(uns, "ssim_scores") or []
        scene = scores[0][0] if scores and scores[0][1] > 0.9 else None
        game = state["game"]
        game["scene"] = scene
        if ns is None:
            return
        game["title"] = (read(ns, "game") or "").strip() or None
        if scene == "elgato_no_signal":
            game["screen"] = "no signal"
        elif read(ns, "home"):
            game["screen"] = "home"
        elif read(ns, "playing"):
            game["screen"] = "playing"
        state["hunt"]["self_encounter"] = bool(read(ns, "self_encounter"))

    def read_controller(self, state):
        """Whether the controller is connected and a macro is running."""
        ns = self.daemon_ns("NXBTDaemon")
        if ns is None:
            return
        controller = state["controller"]
        controller["connected"] = bool(read(ns, "connected"))
        controller["paused"] = bool(read(ns, "pause"))
        controller["looping"] = bool(read(ns, "loop"))
        controller["running"] = bool(read(ns, "playing")) and not controller["paused"]

    def read_events(self, state):
        """When the watchdog, failsafe and last encounter last happened."""
        uns = self.bot.dman.uns
        events = state["events"]
        events["watchdog_at"] = read(uns, "watchdog_at")
        events["watchdog_count"] = read(uns, "watchdog_count", 0) or 0
        events["failsafe_at"] = read(uns, "failsafe_at")
        events["failsafe_count"] = read(uns, "failsafe_count", 0) or 0
        events["encounter_at"] = read(uns, "last_encounter_time")
        state["hunt"]["shiny_pending"] = bool(read(uns, "nxbt_daemon_stop"))

    async def read_hunt(self, state):
        """The hunt target and its encounter log statistics."""
        hunt = state["hunt"]
        hunt["target"] = read(self.bot.args, "hunt") or None
        if not hunt["target"] or not self.bot.drive.enabled:
            return
        lines = await asyncio.to_thread(self.log_lines, hunt["target"])
        log = parse_encounter_log(lines)
        hunt["encounters"] = len(log.encounters)
        if log.encounters:
            hunt["last_encounter"] = log.encounters[-1] / 1000
        if log.first is not None:
            end = log.stopped_at or state["now"] * 1000
            hunt["hunting_seconds"] = (end - log.first - log.paused_ms) / 1000
        hunt["stopped"] = log.stopped_at is not None
        average = average_interval_ms(lines)
        if average:
            hunt["average_seconds"] = average / 1000

    def log_lines(self, hunt):
        """Read the hunt's encounter log."""
        with self.bot.drive.open(encounter_log_name(hunt), "r", touch=True) as f:
            return f.readlines()

    async def read_stream(self, state):
        """OBS output state, plus viewers, title and category from Twitch."""
        stream = state["stream"]
        obs = getattr(self.bot, "obs", None)
        if obs is not None:
            try:
                status = await asyncio.to_thread(obs.status)
                stream["live"] = bool(status["streaming"])
                stream["recording"] = bool(status["recording"])
                if stream["live"]:
                    stream["seconds"] = status["stream_seconds"]
            except Exception:
                stream["live"] = None
        live = await self.twitch_stream()
        if live is not None:
            stream["viewers"] = live.get("viewer_count")
            stream["title"] = live.get("title")
            stream["category"] = live.get("game_name")

    async def twitch_stream(self):
        """The channel's live stream from Twitch, cached for a minute."""
        api = getattr(self.bot, "twitch_api", None)
        channel = self.bot.env.get("TWITCH_CHANNEL", None)
        if api is None or not api.authorized or not channel:
            return None
        if time.monotonic() - self.twitch["at"] > TWITCH_REFRESH_SECONDS:
            self.twitch["at"] = time.monotonic()
            try:
                self.twitch["stream"] = await api.live_stream(channel)
            except Exception as e:
                logger.debug("Couldn't ask Twitch about the stream: %s", e)
        return self.twitch["stream"]


def stream_start(state):
    """Epoch seconds when the current stream went live, or None."""
    seconds = state["stream"]["seconds"]
    return state["now"] - seconds if seconds else None


def render(state):
    """The snapshot as short lines for the model's system prompt."""
    stream = state["stream"]
    controller = state["controller"]
    events = state["events"]
    lines = []
    if stream["live"]:
        line = f"The stream has been live for {duration(stream['seconds'] or 0)}"
        if stream["viewers"] is not None:
            line += f" with {stream['viewers']} viewers"
        lines.append(line + ".")
        if stream["title"]:
            lines.append(f"Stream title: {stream['title']}")
    elif stream["live"] is False:
        lines.append("Not live on Twitch right now.")
    lines.append(
        f"You (Cynthia) were last restarted {duration(state['bot']['uptime'])} ago; "
        "that's only your own uptime, not the hunt's or the stream's."
    )
    if state["bot"]["status"]:
        lines.append(f"Status: {state['bot']['status']}")
    lines += describe(state)
    if controller["connected"] is False:
        lines.append("The bot's virtual controller isn't connected to the Switch.")
    elif controller["connected"]:
        doing = "running the hunting macro" if controller["running"] else "idle"
        if controller["paused"]:
            doing = "paused"
        lines.append(
            "The bot's virtual controller (it presses the Switch's buttons for "
            f"the hunt) is connected and {doing}."
        )
    if events["watchdog_at"]:
        lines.append(
            "The hunt watchdog last restarted a stuck macro "
            f"{ago(state, events['watchdog_at'])}."
        )
    if events["failsafe_at"]:
        lines.append(
            "The macro last got lost and ran its failsafe "
            f"{ago(state, events['failsafe_at'])}."
        )
    return lines
