import discord
from discord.ext import commands
from .messenger import Messenger
from .applications import CommandTree


class Bot(discord.Client):
    def __init__(self, config, *, onexit=None):
        self.config = config
        self.messenger = Messenger(self)
        self.onexit = onexit
        self.owner = config.owner
        self.kill_reason = None
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            intents=intents,
            status=discord.Status.online,
        )
        self.tree = CommandTree(self)

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

    def raise_(self, ExceptionType, /, *args, **kwargs):
        raise ExceptionType()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        print("__aexit__")
        if exc_type is not None:
            if self.kill_reason is not None:
                if not isinstance(self.kill_reason, list):
                    self.kill_reason = [self.kill_reason]
                self.kill_reason.append((exc_type, exc_val, exc_tb))
            else:
                self.kill_reason = (exc_type, exc_val, exc_tb)
        if self.onexit is not None:
            if not self.is_closed():
                await self.messenger.msg_owner("Cynthia is closing. Running cleanup...")
            self.onexit(self.config)
            if not self.is_closed():
                await self.messenger.msg_owner("Cleanup complete.")
        if not self.is_closed():
            await self.messenger.msg_owner("Cynthia will now exit.")
        await super().__aexit__(exc_type, exc_val, exc_tb)
