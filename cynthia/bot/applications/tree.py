import discord.app_commands
import importlib
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

    def load_commands(self):
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
        errors = []
        for module in self.modules:
            logger.debug(f"Loading applications from module: {module} ...")
            application = None
            try:
                if module in self.__previously_loaded_modules:
                    application = importlib.reload_module(
                        "." + module, "cynthia.bot.applications"
                    ).__application__
                else:
                    application = importlib.import_module(
                        "." + module, "cynthia.bot.applications"
                    ).__application__
            except (ImportError, FileNotFoundError, ValueError, KeyError) as e:
                error = (
                    f" ERR.\n\tFailed to load application from module: {module}\n"
                    + f"\tError: {e}"
                )
                logger.error(error)
                errors += error
            if application is not None:
                if hasattr(application, "apps"):
                    _application = application(self.client)
                    application = _application.apps()
                self.__loaded_modules.append(module)
                if hasattr(application, "__iter__"):
                    for command in application:
                        self.add_command(command)
                        self.__loaded_commands.append(f"{module}.{command.name}")
                else:
                    self.add_command(application)
                    self.__loaded_commands.append(f"{module}.{command.name}")
                logger.debug("Done")
            else:
                logger.error(f" ERR.\n\tNo application found in module: {module}")
        return len(self.get_commands()), errors

    def clear_commands(self):
        self.__previously_loaded_modules = getattr(self, "__loaded_modules", list())
        self.__loaded_modules = []
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
