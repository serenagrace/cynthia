"""
Config Loader and handler.
"""

from pathlib import Path

import yaml

from cynthia.utils.snowflake import UserFlake

from .defaults import Defaults


class ConfigLoader:
    """Load default and file-based bot configuration and save updates."""

    def __init__(self, filename):
        """Create a loader for an existing configuration file."""
        if not Path(filename).exists():
            raise FileNotFoundError("Specified config file does not exist.")
        self.filename = filename

    def _load(self):
        """Merge file settings over defaults and normalize the owner ID."""
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
        """Return the cached configuration, loading it on first access."""
        if not hasattr(self, "_config"):
            self._config = self._load()
        return self._config

    def save(self, updated_config):
        """Write updated configuration when it differs from the loaded file."""
        if self._file_config != updated_config:
            with open(self.filename, "w") as f:
                yaml.dump(updated_config, f)
