import discord
from discord.ext import commands
from .messenger import Messenger
from .applications import CommandTree


class Bot(commands.bot.Bot):
    def __init__(self, config, *, onexit=None):
        self.config = config
        self.messenger = Messenger(self)
        self.onexit = onexit
        self.owner = config.owner
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            command_prefix="/",
            intents=intents,
            status=discord.Status.online,
            tree_cls=CommandTree,
        )

    async def on_ready(self):
        if n := self.tree.load_commands():
            print(f"Loading {n} commands...", end="")
            await self.tree.sync()
            print(" Done.")
        msg = "Logged on as", self.user.name
        await self.messenger.msg_owner(msg)
        print(await self.tree.fetch_commands())

    async def on_message(self, message):
        if message.author.id == self.user.id:
            return
        print(message.author.id, self.config.users)
        if message.author.id not in self.config.users:
            return
        await self.messenger.respond(message)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.onexit is not None:
            await self.messenger.msg_owner("Cynthia is closing. Running cleanup...")
            self.onexit(self.config)
            await self.messenger.msg_owner("Cleanup complete.")
        await self.messenger.msg_owner("Cynthia will now exit.")
        await super().__aexit__(exc_type, exc_val, exc_tb)
