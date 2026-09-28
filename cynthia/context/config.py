"""
Config Loader and handler.
"""

from pathlib import Path
import yaml
from .defaults import Defaults
from cynthia.utils.snowflake import UserFlake


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
            config["owner"] = (
                UserFlake(uid=config["owner"]).uid if config.get("owner") else None
            )

        if config is None:
            raise ValueError("Config file is empty or invalid.")

        return config

    def __call__(self):
        if not hasattr(self, "_config"):
            self._config = self._load()
        return self._config

    def save(self, updated_config):
        if self._file_config != updated_config:
            with open(self.filename, "w") as f:
                yaml.dump(updated_config, f)
