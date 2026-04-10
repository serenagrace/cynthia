import asyncio
import discord
import gzip
from pathlib import Path
from .messenger import Messenger
from .applications import CommandTree
from cynthia.utils.nxbt_utils import load_macros, save_macros


class Bot(discord.Client):
    def __init__(self, context, *, onexit=None):
        self.config = context.config
        self.app_meta = context.app_meta
        self.messenger = Messenger(self)
        self.onexit = {}
        if onexit is not None:
            self.onexit["user"] = onexit

        self.onmessage = {}
        self.owner = self.config.owner
        self.kill_reason = None
        self.verify = lambda code: False
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            intents=intents,
            status=discord.Status.online,
        )
        self.logging_enabled = False
        self.tree = CommandTree(self)
        if self.config.drive_path is not None:
            log_path = Path(self.config.drive_path) / "message.log.gz"
            if log_path.parent.exists():
                with gzip.open(log_path, "at", encoding="utf-8") as f:
                    f.write(f"! Logging started at {self.app_meta.run_timestamp}\n")

                self.log_path = log_path
                self.logging_enabled = True

                async def log_stop(*args, **kwargs):
                    self.log_write(
                        f"! Logging stopped at {self.app_meta.run_timestamp}\n"
                    )

                self.onexit["logging"] = log_stop

            load_macros(Path(self.config.drive_path))

            async def macro_cleanup(client):
                save_macros(Path(client.config.drive_path))

            self.onexit["macros"] = macro_cleanup

    def log_write(self, entry):
        if not self.logging_enabled:
            return
        with gzip.open(self.log_path, "at", encoding="utf-8") as f:
            f.write(entry)

    def log_message(self, message):
        log_entry = "{message.created_at}:{message.channel}:{message.author}:{message.jump_url}:{message.content}\n"
        self.log_write(log_entry)

    async def reload_tree(self, interaction=None):
        print("Fetching command modules...")
        n = 0
        n = self.tree.load_commands()
        if n:
            print(f"Loading {n} commands...")
            await self.tree.sync()
            print("Done.")
        embed = discord.Embed(
            title="Cynthia Online.",
            url="https://github.com/serenagrace/cynthia",
            color=0xD700FF,
        )
        embed.add_field(name="Launch Time:", value=f"{self.app_meta.run_timestamp}")
        embed.set_footer(
            text=f"#{self.app_meta.git_hash} {self.app_meta.git_timestamp}"
        )
        if n:
            embed.add_field(
                name="Loaded Commands:",
                value=f"{n} from ({len(self.tree.loaded_modules)}/{len(self.tree.modules)}) modules",
            )
        if interaction is not None:
            await interaction.followup.send(embed=embed)
        else:
            await self.messenger.msg_owner(embed)
        print("Loaded commands:")
        print(
            "\n".join(
                f" - {command.name}" for command in await self.tree.fetch_commands()
            )
        )

    async def on_ready(self):
        await self.reload_tree()

    async def on_message(self, message):
        if message.author.id == self.user.id:
            return

        for unit in self.onmessage.values():
            await unit(message)

        if message.author.id not in self.config.privileged_users:
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
            exit_tasks = self.onexit.values()
            self.onexit = None
            if not self.is_closed():
                await self.messenger.msg_owner("Cynthia is closing. Running cleanup...")
            for func in exit_tasks:
                try:
                    await asyncio.wait_for(func(self), timeout=30)
                except TimeoutError:
                    print("Warning: cleanup task timed out.")
            if not self.is_closed():
                try:
                    await self.messenger.msg_owner("Cleanup complete.")
                except:
                    pass
        if not self.is_closed():
            await self.messenger.msg_owner("Cynthia will now exit.")
        await super().__aexit__(exc_type, exc_val, exc_tb)
