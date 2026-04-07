"""
Config Loader and handler.
"""

from pathlib import Path
import yaml
from cynthia.utils.types import force_obj_is_list

from .defaults import Defaults


class ConfigLoader:
    def __init__(self, filename):
        if not Path(filename).exists():
            raise FileNotFoundError("Specified config file does not exist.")
        self.filename = filename

    def _load(self):
        config = None
        with open(self.filename, "r") as f:
            self._file_config = yaml.load(f, Loader=yaml.Loader)
            self._default_config = Defaults().config
            config = {**self._default_config, **self._file_config}

        if config is None:
            raise ValueError("Config file is empty or invalid.")

        privilege_lists = ("privileged_users", "nxbt_users", "drive_users")

        for privilege_list in privilege_lists:
            config[privilege_list] = force_obj_is_list(config[privilege_list])

            if config["owner"] is not None:
                if config["owner"] not in config[privilege_list]:
                    config[privilege_list].append(config["owner"])

        return config

    def __call__(self):
        if not hasattr(self, "_config"):
            self._config = self._load()
        return self._config

    def save(self, updated_config):
        if self._file_config != updated_config:
            with open(self.filename, "w") as f:
                yaml.dump(updated_config, f)
