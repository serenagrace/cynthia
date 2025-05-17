"""
Config Loader and handler.
"""

from pathlib import Path
import yaml
from utils.types import force_obj_is_list

from .defaults import Defaults


class ConfigLoader:
    def __init__(self, filename):
        if not Path(filename).exists():
            raise FileNotFoundError("Specified config file does not exist.")
        self.filename = filename

    def __call__(self):
        with open(self.filename, "r") as f:
            config = {**Defaults.config, **yaml.load(f, Loader=yaml.Loader)}

        config["users"] = force_obj_is_list(config["users"])

        if config["owner"] is not None:
            if config["owner"] not in config["users"]:
                config["users"].append(config["owner"])
        return config

    def save(self, updated_config):
        pass
