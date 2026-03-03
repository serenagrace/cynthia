import discord.app_commands
import importlib


class CommandTree(discord.app_commands.CommandTree):

    __modules = ["config", "control", "status", "shell", "drive", "test", "help", "roku"]
    __loaded_modules = []

    def load_commands(self):
        print(f"{len(self.modules)} command modules found.")
        for module in self.modules:
            print(f"Loading applications from module: {module} ...", end="")
            application = None
            try:
                application = importlib.import_module(
                    "." + module, "cynthia.bot.applications"
                ).__application__
            except (ImportError, FileNotFoundError, ValueError, KeyError) as e:
                print(f" ERR.\n\tFailed to load application from module: {module}")
                print(f"\tError: {e}")
            if application is not None:
                self.__loaded_modules.append(module)
                if hasattr(application, "__iter__"):
                    for command in application:
                        self.add_command(command)
                else:
                    self.add_command(application)
                print(" Done.")
            else:
                print(f" ERR.\n\tNo application found in module: {module}")
        return len(self.get_commands())

    @property
    def modules(self):
        return self.__modules

    @property
    def loaded_modules(self):
        return self.__loaded_modules
