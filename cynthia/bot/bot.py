"""Discord bot implementation and lifecycle management."""

import asyncio
import gzip
import importlib.resources
import logging
from pathlib import Path

import discord
from discord.ext import commands

from cynthia.daemons import DMan
from cynthia.utils import Namespace
from cynthia.utils.db import Database
from cynthia.utils.drive import Drive
from cynthia.utils.logger import Logger
from cynthia.utils.nxbt_utils import load_macros, save_macros
from cynthia.utils.onmessage import OnMessage, load_onmessage, save_onmessage
from cynthia.utils.strings import color_str

from .applications import CommandTree, TreeLoadError
from .messenger import Messenger

_logger = logging.getLogger(__name__)
_logger.setLevel(logging.DEBUG)


class Bot(commands.Bot):
    """Configure Discord integrations, commands, daemons, and cleanup."""

    def __init__(self, context, *, onexit=None, test_mode=False, test_guild_id=None):
        """Initialize bot services and optionally disable daemons for tests."""
        if test_mode and test_guild_id is None:
            raise ValueError("Test mode requires an explicit test guild ID.")
        self.test_mode = test_mode
        self.command_guild_id = test_guild_id
        self.config = context.config
        self.app_meta = context.app_meta
        self.args = context.args
        self.messenger = Messenger(self)
        self.drive = Drive(self.config.drive_path)
        self.database = Database(self.drive)
        if test_mode:
            self.dman = _DisabledDMan()
        else:
            self.dman = DMan(context)
        self.onexit = {}
        if onexit is not None:
            self.onexit["user"] = onexit

        self.owner = self.config.owner
        self.kill_reason = None
        self.verify = lambda code: False
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(
            intents=intents,
            status=discord.Status.idle,
            command_prefix="!!!!!!!!!!!",
            tree_cls=CommandTree,
            help_command=None,
        )
        self.logging_enabled = self.drive.enabled
        self.logger = Logger(self.drive, self.database)
        self.permsloader = context.permsloader
        if self.logger.logging_enabled:
            self.onexit["logging"] = self.logger.log_stop

            load_macros(self.drive)

            async def onmessage_cleanup(*_):
                """Persist message handlers during bot shutdown."""
                save_onmessage(self.database)

            self.onexit["onmessage"] = onmessage_cleanup

        async def dman_cleanup(*_):
            """Stop all managed daemons during bot shutdown."""
            await self.dman.stop_daemons()

        self.onexit["dman"] = dman_cleanup
        self.discovered_cogs = list()
        self.loaded_command_count = 0
        self.loaded_cog_count = 0

    async def reload_tree(self, interaction=None):
        """Load command modules, sync commands, and report reload results."""
        _logger.info("Fetching command modules...")
        n = 0
        n, errors = await self.tree.load_commands()
        if n:
            self.loaded_command_count = n
            _logger.info(f"Loading {n} commands...")
            for error in errors:
                _logger.error(error)
            await self._sync_command_tree()
            _logger.info("Done.")
        if not self.test_mode:
            await self.wake_message(interaction, errors)

        _logger.info("Loaded commands.")
        fetched_commands = (
            await self.tree.fetch_commands(
                guild=discord.Object(id=self.command_guild_id)
            )
            if self.test_mode
            else await self.tree.fetch_commands()
        )
        _logger.debug(
            "\n" + "\n".join(f" - {command.name}" for command in fetched_commands)
        )

    async def reload_application(self, module):
        """Reload one command module and sync the updated command tree."""
        errors = await self.tree.reload_module(module)
        self.loaded_command_count = len(self.tree.get_commands())
        await self._sync_command_tree()
        return errors

    async def _sync_command_tree(self):
        """Sync commands globally or to the configured test guild."""
        if self.test_mode:
            guild = discord.Object(id=self.command_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            return
        await self.tree.sync()
        guild = discord.Object(id="1061724997330157669")
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

    async def get_all_guilds(self) -> list:
        """Returns guilds from local cache, or fetches them from the API if cache is empty."""
        # 1. Try reading directly from memory cache
        if self.guilds:
            return self.guilds

        # 2. Fallback to API lookup if cache isn't filled yet
        try:
            # fetch_guilds returns an AsyncIterator; we flatten it into a list
            return [guild async for guild in self.fetch_guilds(limit=None)]
        except Exception as e:
            print(f"Failed to fetch guilds from API: {e}")
            return []

    def _discover_cogs(self, traversable, current_pkg: str):
        """Recursively find cog modules beneath a package directory."""
        cog_extensions = []

        for item in traversable.iterdir():
            if item.is_dir() and not item.name.startswith("__"):
                cog_extensions.extend(
                    self._discover_cogs(item, f"{current_pkg}.{item.name}")
                )
            elif (
                item.is_file()
                and item.name.endswith(".py")
                and not item.name.startswith("__")
            ):
                cog_name = item.stem
                cog_extensions.append(f"{current_pkg}.{cog_name}")

        return cog_extensions

    async def load_cogs(self):
        """Discover and load cog extensions, logging individual failures."""
        _logger.info("Loading cogs...")
        cogs_pkg_path = "cynthia.bot.cogs"
        cogs_pkg = importlib.resources.files(cogs_pkg_path)

        count = 0
        self.discovered_cogs = self._discover_cogs(cogs_pkg, cogs_pkg_path)
        for cog in self.discovered_cogs:
            try:
                await self.load_extension(cog)
                _logger.info(f"Loaded cog: {cog}")
                count += 1
            except Exception as e:
                _logger.error(f"Failed to load cog {cog}: {e}")

        if count > 0:
            _logger.info(f" {count} cog{'s' if count != 1 else ''} loaded.")
        else:
            _logger.warning("No cogs loaded.")
        self.loaded_cog_count = count

    async def reload_cog(self, extension):
        """Reload one cog; discord.py rolls back to the old cog if the new one fails."""
        self.discovered_cogs = self._discover_cogs(
            importlib.resources.files("cynthia.bot.cogs"), "cynthia.bot.cogs"
        )
        if extension not in self.discovered_cogs:
            return f"Unknown cog: {extension}"
        try:
            if extension in self.extensions:
                await self.reload_extension(extension)
            else:
                await self.load_extension(extension)
        except Exception as e:
            _logger.error(f"Failed to reload cog {extension}: {e!r}")
            return repr(e)
        self.loaded_cog_count = len(self.extensions)
        await self._sync_command_tree()
        return None

    async def setup_hook(self):
        """Load permissions, cogs, and application commands during startup."""
        guilds = [] if self.test_mode else await self.get_all_guilds()
        _logger.info(f"Currently member in {len(guilds)} guilds.")
        self.perms = Namespace(self.permsloader(self))
        self.perms_check = self.permsloader.check
        await self.load_cogs()
        await self.reload_tree()

    async def on_ready(self):
        """Load message handlers and mark the bot as online."""
        await load_onmessage(self)
        _logger.info(color_str("Ready.", "yellow"))
        await self.change_presence(status=discord.Status.online)

    async def on_message(self, message):
        """Run registered message handlers and respond to permitted messages."""
        if message.author.id == self.user.id:
            return

        for key, unit in OnMessage.units.items():
            if await unit.call(self, message):
                _logger.debug(f"Ran onmessage unit: {key}")

        try:
            if not self.perms_check(
                Namespace(
                    {
                        "user": message.author,
                        "guild_id": getattr(message, "guild_id", None),
                    }
                ),
                perm="privileged",
            ):
                return
        except Exception as e:
            _logger.error(f"Error checking permissions: {e}")
            return
        await self.messenger.respond(message)

    async def wake_message(self, interaction=None, errors=None):
        """Report startup status and command-loading errors to the owner."""
        if errors is None:
            errors = list()
        embed = discord.Embed(
            title="Cynthia Online.",
            url="https://github.com/serenagrace/cynthia",
            color=0xD700FF,
        )
        embed.add_field(name="Launch Time:", value=f"{self.app_meta.run_timestamp}")
        embed.set_footer(
            text=f"#{self.app_meta.git_hash} {self.app_meta.git_timestamp}"
        )
        if self.loaded_command_count:
            embed.add_field(
                name="Loaded Commands:",
                value=f"{self.loaded_command_count} from {'⚠️' if len(self.tree.loaded_modules) != len(self.tree.modules) else ''}({len(self.tree.loaded_modules)}/{len(self.tree.modules)}) modules",
            )
        if self.loaded_cog_count:
            embed.add_field(
                name="Loaded Cogs:",
                value=f"{self.loaded_cog_count} from {'⚠️' if self.loaded_cog_count != len(self.discovered_cogs) else ''}({self.loaded_cog_count}/{len(self.discovered_cogs)}) modules",
            )
        if len(errors):
            embed.add_field(
                name="Errors:",
                value="-"
                + "\n-".join(errors[:3])
                + ("\n..." if len(errors) > 3 else ""),
            )
        if interaction is not None:
            await interaction.followup.send(embed=embed)
        else:
            await self.messenger.msg_owner(embed, alert=True)

    async def close(self):
        """Run registered cleanup tasks before closing the Discord client."""
        if self.onexit is not None:
            exit_tasks = self.onexit.values()
            self.onexit = None
            if not self.is_closed():
                await self.messenger.msg_owner("Cynthia is closing. Running cleanup...")
            for func in exit_tasks:
                try:
                    await asyncio.wait_for(func(self), timeout=60)
                except TimeoutError:
                    _logger.warn("Warning: cleanup task timed out.")
            if not self.is_closed():
                try:
                    await self.messenger.msg_owner("Cleanup complete.")
                except:
                    pass
        if not self.is_closed():
            await self.messenger.msg_owner("Cynthia will now exit.")
        await super().close()

    def raise_(self, ExceptionType, /, *args, **kwargs):
        """Raise an exception type, matching the client's callback interface."""
        raise ExceptionType()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Record shutdown exceptions and delegate client exit handling."""
        if exc_type is not None:
            if self.kill_reason is not None:
                if not isinstance(self.kill_reason, list):
                    self.kill_reason = [self.kill_reason]
                self.kill_reason.append((exc_type, exc_val, exc_tb))
            else:
                self.kill_reason = (exc_type, exc_val, exc_tb)
        await super().__aexit__(exc_type, exc_val, exc_tb)


class _DisabledDMan:
    """No-op daemon manager used when the bot runs in test mode."""

    def __init__(self):
        """Initialize empty daemon state for test-mode operation."""
        self.running_daemons = {}
        self.uns = Namespace({"nxbt_daemon_stop": False, "nxbt_connection_lost": False})

    async def stop_daemons(self):
        """Match the daemon manager shutdown API without starting daemons."""
        return None
