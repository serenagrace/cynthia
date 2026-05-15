import discord
import io
from discord.ext import tasks, commands
import itertools


class StatusCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.hunt_cycle = itertools.cycle(["game", "hunt", "count"])

    async def cog_load(self):
        self.get_status.start()

    @tasks.loop(seconds=15.0)
    async def get_status(self):

        def tryload(bot):
            ns = None
            cv = bot.dman.running_daemons.get("CVDaemon", None)
            if cv is not None:
                ns = getattr(cv, "ns", None)
            return ns

        ns = tryload(self.bot)
        if ns is None:
            return

        if ns.game is not None:
            if not hasattr(self, "remembered_game") or self.remembered_game != ns.game:
                self.remembered_game = ns.game

        game = (
            ns.game if ns.game is not None else getattr(self, "remembered_game", None)
        )

        if ns.home:
            await self.bot.change_presence(
                activity=discord.Game(name="on the Home Screen")
            )

        elif ns.playing:
            if game is not None:
                if self.bot.args.hunt:
                    state = next(self.hunt_cycle)
                    if state == "game":
                        if game is not None:
                            await self.bot.change_presence(
                                activity=discord.Game(name=game)
                            )
                    if state == "hunt":
                        state_str = f"Hunting {self.bot.args.hunt.title()}"
                        await self.bot.change_presence(
                            activity=discord.CustomActivity(name=state_str)
                        )

                    elif state == "count":
                        count = None
                        state_str = "No encounters yet"
                        with self.bot.drive.open(
                            "encounter_times.log", "r", touch=True
                        ) as f:
                            count = sum(1 for _ in f)
                        if count:
                            state_str = f"{count} encounters"
                        await self.bot.change_presence(
                            activity=discord.CustomActivity(name=state_str)
                        )
                else:
                    await self.bot.change_presence(activity=discord.Game(name=game))
        else:
            await self.bot.change_presence(activity=None)
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

    @get_status.before_loop
    async def before_status(self):
        # Essential: Wait until bot is connected
        await self.bot.wait_until_ready()
