import discord
from discord.ext import tasks, commands


class StatusCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.get_status.start()

    @tasks.loop(seconds=2.0)
    async def get_status(self):
        if self.bot.uvc.ns.home:
            await self.bot.change_presence(
                activity=discord.Game(name="on the Home Screen")
            )
        elif self.bot.uvc.ns.playing:
            await self.bot.change_presence(
                activity=discord.Game(name=self.bot.uvc.ns.game)
            )
        else:
            await self.bot.change_presence(activity=None)

    @get_status.before_loop
    async def before_status(self):
        # Essential: Wait until bot is connected
        await self.bot.wait_until_ready()
