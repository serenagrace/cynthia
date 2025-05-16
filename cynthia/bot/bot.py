import discord
from discord.ext import commands
from .messenger import Messenger


class Bot(commands.bot.Bot):
    def __init__(self, config):
        self.config = config
        self.messenger = Messenger(self)
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            command_prefix="/", intents=intents, status=discord.Status.online
        )

    async def on_ready(self):
        msg = "Logged on as", self.user.name
        await self.messenger.msg_owner(msg)

    async def on_message(self, message):
        await self.messenger.respond(message)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        print("Caught exit")
        await self.messenger.msg_owner("Cynthia is closing.")
        await super().__aexit__(exc_type, exc_val, exc_tb)
