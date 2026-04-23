import asyncio
import discord
import gzip
from pathlib import Path
from .messenger import Messenger
from .applications import CommandTree, TreeLoadError
from cynthia.utils.db import Database
from cynthia.utils.drive import Drive
from cynthia.utils.logger import Logger
from cynthia.utils.nxbt_utils import load_macros, save_macros
from cynthia.utils.onmessage import load_onmessage, save_onmessage, ONMESSAGE
from cynthia.utils.strings import color_str
from cynthia.utils.uvc import UVC
import logging

_logger = logging.getLogger(__name__)
_logger.setLevel(logging.DEBUG)


class Bot(discord.Client):
    def __init__(self, context, *, onexit=None):
        self.config = context.config
        self.app_meta = context.app_meta
        self.messenger = Messenger(self)
        self.drive = Drive(self.config.drive_path)
        self.database = Database(self.drive)
        self.uvc = UVC()
        self.onexit = {}
        if onexit is not None:
            self.onexit["user"] = onexit

        self.owner = self.config.owner
        self.kill_reason = None
        self.verify = lambda code: False
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            intents=intents,
            status=discord.Status.online,
        )
        self.logging_enabled = self.drive.enabled
        self.tree = CommandTree(self)
        self.logger = Logger(self.drive, self.database)
        if self.logger.logging_enabled:
            self.onexit["logging"] = self.logger.log_stop

            load_macros(self.drive)
            load_onmessage(self)

            async def macro_cleanup(*_):
                save_macros(self.drive)

            async def onmessage_cleanup(*_):
                save_onmessage(self.database)

            self.onexit["macros"] = macro_cleanup
            self.onexit["onmessage"] = onmessage_cleanup

        async def uvc_cleanup(*_):
            self.uvc.release()

        self.onexit["uvc"] = uvc_cleanup

    async def reload_tree(self, interaction=None):
        _logger.info("Fetching command modules...")
        n = 0
        n, errors = self.tree.load_commands()
        if n:
            _logger.info(f"Loading {n} commands...")
            for error in errors:
                _logger.error(error)
            await self.tree.sync()
            _logger.info("Done.")
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
                value=f"{n} from {'⚠️' if len(self.tree.loaded_modules) != len(self.tree.modules) else ''}({len(self.tree.loaded_modules)}/{len(self.tree.modules)}) modules",
            )
        if len(errors):
            embed.add_field(
                name="Errors:",
                value="-"
                + "\n-".join(errors[:3])
                + ("\n..." if len(errors > 2) else ""),
            )
        if interaction is not None:
            await interaction.followup.send(embed=embed)
        else:
            await self.messenger.msg_owner(embed, alert=True)
        _logger.info("Loaded commands.")
        _logger.debug(
            "\n"
            + "\n".join(
                f" - {command.name}" for command in await self.tree.fetch_commands()
            )
        )

    async def on_ready(self):
        await self.reload_tree()
        _logger.info(color_str("Ready.", "yellow"))

    async def on_message(self, message):
        if message.author.id == self.user.id:
            return

        for key, unit in ONMESSAGE.items():
            _logger.debug(f"Running onmessage unit: {key}")
            await unit.call(self, message)

        if message.author.id not in self.config.privileged_users:
            return
        await self.messenger.respond(message)

    def raise_(self, ExceptionType, /, *args, **kwargs):
        raise ExceptionType()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
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
                    _logger.warn("Warning: cleanup task timed out.")
            if not self.is_closed():
                try:
                    await self.messenger.msg_owner("Cleanup complete.")
                except:
                    pass
        if not self.is_closed():
            await self.messenger.msg_owner("Cynthia will now exit.")
        await super().__aexit__(exc_type, exc_val, exc_tb)
