"""Cog that updates Discord activity and publishes user status."""

import io
import itertools
import json

import discord
from discord.ext import commands, tasks

from cynthia.utils.encounters import (
    average_interval_ms,
    encounter_log_name,
    parse_encounter_log,
)


class StatusCog(commands.Cog):
    """Derive bot and rich-presence status from daemon state."""

    def __init__(self, bot):
        """Initialize status state and the rotating hunt activity cycle."""
        self.bot = bot
        self.status_cycle = None
        self.bot_activity = None
        self.user_activity = None

    async def cog_load(self):
        """Start the periodic presence and user-status update tasks."""
        self.set_status.start()
        self.update_status.start()

    @tasks.loop(seconds=3.0)
    async def update_status(self):
        """Refresh status data and write the user-facing status file."""
        bot_activity, self.user_activity = await self.get_status()
        if bot_activity != self.bot_activity:
            self.bot_activity = bot_activity
            if self.bot_activity is not None:
                if isinstance(self.bot_activity, list):
                    self.status_cycle = itertools.cycle(self.bot_activity)
                else:
                    self.status_cycle = None
        if self.bot.drive.enabled:
            with self.bot.drive.open("user_status.json", "w") as f:
                json.dump(self.user_activity, f, indent=4)
            with self.bot.drive.open("activity_stats.json", "w") as f:
                json.dump(self.get_activity_stats(), f, indent=4)

    def get_activity_stats(self):
        """Return raw timestamps (epoch ms) for the site to turn into durations.

        Active hunt time is (hunt_stopped_at or now) - (hunt_started + hunt_correction_ms),
        where the correction is time spent not hunting in completed stop/start pauses.
        """
        stats = {"bot_started": self.bot.started_at_ms}
        if self.bot.args.hunt and self.bot.drive.enabled:
            with self.bot.drive.open(
                encounter_log_name(self.bot.args.hunt), "r", touch=True
            ) as f:
                lines = f.readlines()
            log = parse_encounter_log(lines)
            if log.first is not None:
                stats["hunt_started"] = log.first
                stats["hunt_correction_ms"] = log.paused_ms
            if log.stopped_at is not None:
                stats["hunt_stopped_at"] = log.stopped_at
            if log.encounters:
                stats["last_encounter"] = log.encounters[-1]
            average_ms = average_interval_ms(lines)
            if average_ms is not None:
                stats["average_interval_ms"] = round(average_ms)
        return stats

    @tasks.loop(seconds=15.0)
    async def set_status(self):
        """Update Discord presence, rotating through hunt activity values."""
        activity = self.bot_activity
        if self.status_cycle is not None:
            activity = next(self.status_cycle)
        await self.bot.change_presence(activity=activity)

    async def get_status(self):
        """Build Discord and rich-presence status from computer-vision state."""
        bot_activity = None
        user_activity = None

        def tryload(bot):
            """Return the computer-vision daemon namespace when available."""
            ns = None
            cv = bot.dman.running_daemons.get("CVDaemon", None)
            if cv is not None:
                ns = getattr(cv, "ns", None)
            return ns

        ns = tryload(self.bot)
        if ns is None:
            return bot_activity, user_activity

        if ns.game is not None:
            if not hasattr(self, "remembered_game") or self.remembered_game != ns.game:
                self.remembered_game = ns.game

        game = (
            ns.game if ns.game is not None else getattr(self, "remembered_game", None)
        )

        if ns.home:
            bot_activity = discord.Game(name="on the Home Screen")
            user_activity = {
                "type": "playing",
                "name": "Nintendo Switch",
                "details": "on the Home Screen",
                "assets": {"large_image": "nintendo_switch"},
            }

        elif ns.playing:
            encounter_str = "No encounters yet"
            if game is not None:
                large_image = "nintendo_switch"
                if "diamond" in game.lower():
                    large_image = "dialga_glow"
                elif "pearl" in game.lower():
                    large_image = "palkia_glow"
                if self.bot.args.hunt:
                    if ns.self_encounter:
                        hunting_str = "Looking for "
                        encounter_str = "No attempts yet"
                    else:
                        hunting_str = "Hunting "
                    hunting_str += f"shiny {self.bot.args.hunt.title()}"
                    log = parse_encounter_log([])
                    if self.bot.drive.enabled:
                        with self.bot.drive.open(
                            encounter_log_name(self.bot.args.hunt), "r", touch=True
                        ) as f:
                            log = parse_encounter_log(f.readlines())
                    count = len(log.encounters)

                    if count:
                        if ns.self_encounter:
                            encounter_str = f"{count} resets"
                        else:
                            encounter_str = f"{count} encounters"

                    bot_activity = [
                        discord.Game(name=game),
                        discord.CustomActivity(name=hunting_str),
                        discord.CustomActivity(name=encounter_str),
                    ]
                    user_activity = {
                        "type": "playing",
                        "name": game,
                        "details": hunting_str,
                        "state": encounter_str,
                        "timestamps": {
                            "start": log.first,
                            "correction": log.paused_ms,
                        },
                        "assets": {"large_image": large_image},
                    }
                elif self.bot.vars.status.text is not None:
                    bot_activity = [
                        discord.Game(name=game),
                        discord.CustomActivity(name=self.bot.vars.status.text),
                    ]
                    user_activity = {
                        "type": "playing",
                        "name": game,
                        "details": self.bot.vars.status.text,
                        "assets": {"large_image": large_image},
                    }
                    if self.bot.vars.status.start is not None:
                        user_activity["timestamps"] = {
                            "start": int(self.bot.vars.status.start.timestamp() * 1000)
                        }
                else:
                    bot_activity = discord.Game(name=game)
                    user_activity = {
                        "type": "playing",
                        "name": game,
                        "assets": {"large_image": large_image},
                    }
        elif self.bot.vars.status.text is not None:
            bot_activity = discord.CustomActivity(name=self.bot.vars.status.text)
        else:
            bot_activity = None
        shiny_stop = getattr(self.bot.dman.uns, "nxbt_daemon_stop", False)
        connection_lost = getattr(self.bot.dman.uns, "nxbt_connection_lost", False)
        if connection_lost:
            await self.bot.messenger.msg_owner(
                "Connection to NXBTDaemon lost!", alert=True
            )
            self.bot.dman.uns.nxbt_connection_lost = False
        if getattr(self.bot.dman.uns, "watchdog_triggered", False):
            self.bot.dman.uns.watchdog_triggered = False
            await self.bot.messenger.msg_owner(
                "Hunt watchdog triggered: no encounter for too long, "
                "restarted the current macro.",
                alert=True,
            )
        recovered = getattr(self.bot.dman.uns, "quick_settings_recovered", 0)
        if recovered:
            self.bot.dman.uns.quick_settings_recovered = 0
            await self.bot.messenger.msg_owner(
                f"Quick settings menu opened by a stretched HOME press "
                f"({recovered}x); closed it and retried.",
                alert=True,
            )
        if shiny_stop:
            messaged = getattr(self.bot.dman.uns, "messaged", False)
            if not messaged:
                embed, buffer = ns.embed, ns.png
                io_buf = io.BytesIO(buffer)
                io_buf.seek(0)
                png = discord.File(fp=io_buf, filename="frame.png")
                await self.bot.messenger.msg_owner(
                    "Possible shiny found!", embed=embed, file=png, alert=True
                )
                self.bot.dman.uns.messaged = True
        return bot_activity, user_activity

    @set_status.before_loop
    async def before_status(self):
        """Wait for the bot connection before starting the status loop."""
        # Essential: Wait until bot is connected
        await self.bot.wait_until_ready()


async def setup(bot):
    """Register the status cog with the bot."""
    await bot.add_cog(StatusCog(bot))
