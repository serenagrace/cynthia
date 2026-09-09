import discord
import io
from discord.ext import tasks, commands
import itertools
from datetime import datetime
import json


class StatusCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.hunt_cycle = itertools.cycle(["game", "hunt", "count"])
        self.bot_activity = None
        self.user_activity = None

    async def cog_load(self):
        self.set_status.start()
        self.update_status.start()

    @tasks.loop(seconds=3.0)
    async def update_status(self):
        self.bot_activity, self.user_activity = await self.get_status()
        with self.bot.drive.open("user_status.json", "w") as f:
            json.dump(self.user_activity, f, indent=4)

    @tasks.loop(seconds=15.0)
    async def set_status(self):
        activity = self.bot_activity
        if isinstance(self.bot_activity, dict):
            activity = self.bot_activity.get(next(self.hunt_cycle), None)
        await self.bot.change_presence(activity=activity)

    async def get_status(self):
        bot_activity = None
        user_activity = None

        def tryload(bot):
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
            if game is not None:
                large_image = "nintendo_switch"
                if "diamond" in game.lower():
                    large_image = "dialga_glow"
                elif "pearl" in game.lower():
                    large_image = "palkia_glow"
                if self.bot.args.hunt:
                    hunting_str = f"Hunting {self.bot.args.hunt.title()}"
                    encounter_str = "No encounters yet"
                    start = None
                    count = None
                    with self.bot.drive.open(
                        "encounter_times.log", "r", touch=True
                    ) as f:
                        lines = f.readlines()
                        count = sum(1 for _ in lines)
                        if lines:
                            start = int(
                                datetime.strptime(
                                    lines[0].split(",")[0].strip(),
                                    "%Y-%m-%d %H:%M:%S.%f",
                                ).timestamp()
                                * 1000
                            )

                    if count:
                        encounter_str = f"{count} encounters"

                    bot_activity = {
                        "game": discord.Game(name=game),
                        "hunt": discord.CustomActivity(name=hunting_str),
                        "count": discord.CustomActivity(name=encounter_str),
                    }
                    user_activity = {
                        "type": "playing",
                        "name": game,
                        "details": hunting_str,
                        "state": encounter_str,
                        "timestamps": {"start": start},
                        "assets": {"large_image": large_image},
                    }
                else:
                    bot_activity = discord.Game(name=game)
                    user_activity = {
                        "type": "playing",
                        "name": game,
                        "assets": {"large_image": large_image},
                    }
        else:
            bot_activity = None
        shiny_stop = getattr(self.bot.dman.uns, "nxbt_daemon_stop", False)
        connection_lost = getattr(self.bot.dman.uns, "nxbt_connection_lost", False)
        if connection_lost:
            await self.bot.messenger.msg_owner(
                "Connection to NXBTDaemon lost!", alert=True
            )
            self.bot.dman.uns.nxbt_connection_lost = False
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
        # Essential: Wait until bot is connected
        await self.bot.wait_until_ready()
