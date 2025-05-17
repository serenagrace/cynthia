import discord.app_commands
import importlib


class CommandTree(discord.app_commands.CommandTree):

    __modules = ["config"]
    __loaded_modules = []

    def load_commands(self):
        for module in self.modules:
            command_list = None
            try:
                application = importlib.import_module(
                    "." + module, ".bot.applications"
                ).__application__
            except (ImportError, FileNotFoundError, ValueError, KeyError):
                pass
            if application is not None:
                self.__loaded_modules.append(module)
                if hasattr(application, "__iter__"):
                    for command in application:
                        self.add_command(command)
                else:
                    self.add_command(application())
        return len(self.get_commands())

    @property
    def modules(self):
        return self.__modules

    @property
    def loaded_modules(self):
        return self.loaded_modules
