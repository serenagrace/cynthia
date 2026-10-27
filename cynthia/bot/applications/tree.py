import discord.app_commands
import importlib
import sys
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class TreeLoadError(Exception):
    def __init__(self, message):
        super().__init__(message)


class CommandTree(discord.app_commands.CommandTree):

    def __init__(self, client):
        self.client = client
        super().__init__(client)

    async def on_error(self, interaction, error):
        if isinstance(error, discord.app_commands.CheckFailure):
            message = str(error) or "You do not have permission to use this command."
            message = f"❌ {message}"
        else:
            logger.error("Unhandled command error", exc_info=error)
            message = "❌ Something went wrong running that command."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    async def load_commands(self):
        importlib.invalidate_caches()
        self.clear_commands()
        self.__directory = Path(__file__).parent
        self.__modules = [
            module.stem
            for module in Path(__file__).parent.glob("*.py")
            if module.stem != "__init__" and module.stem != "tree"
        ]
        logger.debug(
            f"{len(self.modules)} command modules found in {self.application_directory}."
        )
        errors = list()
        for module in self.modules:
            error = await self._load_module(module)
            if error:
                errors.append(error)
        return len(self.get_commands()), errors

    async def _load_module(self, module):
        """Import (or reload) one application module and register its commands."""
        logger.debug(f"Loading applications from module: {module} ...")
        name = f"cynthia.bot.applications.{module}"
        try:
            if name in sys.modules:
                imported = importlib.reload(sys.modules[name])
            else:
                imported = importlib.import_module(name)
            application = imported.__application__
        except Exception as e:
            error = (
                f" ERR.\n\tFailed to load application from module: {module}\n"
                + f"\tError: {e!r}"
            )
            logger.error(error)
            return error

        commands = []
        if hasattr(application, "apps"):
            _application = application(self.client)
            if hasattr(_application, "__ainit__"):
                await _application.__ainit__()
            application = _application.apps()
        if not hasattr(application, "__iter__"):
            application = [application]
        for command in application:
            if hasattr(command, "apps"):
                _subapplication = command(self.client)
                if hasattr(_subapplication, "__ainit__"):
                    await _subapplication.__ainit__()
                commands.extend(_subapplication.apps())
            else:
                commands.append(command)
        for command in commands:
            self.add_command(command)
            self.__loaded_commands.append(f"{module}.{command.name}")
        self.__module_commands[module] = [command.name for command in commands]
        self.__loaded_modules.append(module)
        logger.debug("Done")
        return None

    async def reload_module(self, module):
        """Reload a single application module without touching the others."""
        if module not in self.modules:
            return [f"Unknown application module: {module}"]
        previous = self.__module_commands.get(module, [])
        old_commands = [self.get_command(name) for name in previous]
        for name in previous:
            self.remove_command(name)
        self.__loaded_commands = [
            c for c in self.__loaded_commands if not c.startswith(f"{module}.")
        ]
        if module in self.__loaded_modules:
            self.__loaded_modules.remove(module)
        error = await self._load_module(module)
        if error:
            # Broken new code: keep the previously working commands
            for command in old_commands:
                if command is not None:
                    self.add_command(command)
            self.__module_commands[module] = previous
            self.__loaded_modules.append(module)
        return [error] if error else []

    def clear_commands(self):
        self.__loaded_modules = []
        self.__module_commands = {}
        self.__loaded_commands = []
        super().clear_commands(guild=None)

    @property
    def modules(self):
        return self.__modules

    @property
    def loaded_modules(self):
        return self.__loaded_modules

    @property
    def application_directory(self):
        return self.__directory

    @property
    def loaded_commands(self):
        return self.__loaded_commands
