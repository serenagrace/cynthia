import discord
import io
from discord.ext import tasks, commands


class StatusCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.get_status.start()

    @tasks.loop(seconds=2.0)
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

        if ns.home:
            await self.bot.change_presence(
                activity=discord.Game(name="on the Home Screen")
            )
        elif ns.playing:
            if ns.game is not None:
                await self.bot.change_presence(activity=discord.Game(name=ns.game))
        else:
            await self.bot.change_presence(activity=None)
        shiny_stop = getattr(self.bot.dman.uns, "nxbt_daemon_stop", False)
        if shiny_stop:
            messaged = getattr(self.bot.dman.uns, "messaged", False)
            if not messaged:
                embed, buffer = ns.embed, ns.png
                io_buf = io.BytesIO(buffer)
                io_buf.seek(0)
                png = discord.File(fp=io_buf, filename="frame.png")
                await self.bot.messenger.msg_owner("Possible shiny found!", embed=embed, file=png, alert=True)
                self.bot.dman.uns.messaged = True

    @get_status.before_loop
    async def before_status(self):
        # Essential: Wait until bot is connected
        await self.bot.wait_until_ready()
