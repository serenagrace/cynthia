"""Load and expose the bot's runtime configuration and metadata."""

from cynthia.utils import Namespace

from .app_info import get_app_info
from .config import ConfigLoader
from .env import EnvLoader
from .perms import PermsLoader


class Context:
    """Collect configuration, permissions, environment, and app metadata."""

    def __init__(self, args):
        """Load runtime state using paths and options from parsed arguments."""
        self.configloader = ConfigLoader(args.config)
        self.permsloader = PermsLoader(args.perms)
        self.env = Namespace(EnvLoader(".env")())
        self.config = Namespace(self.configloader())
        self.perms = Namespace(PermsLoader.default())
        self.app_meta = Namespace(get_app_info())
        self.args = Namespace(vars(args))
        self.vars = Namespace({"status": Namespace({"start": None, "text": None})})

    def update_config(self, updated_config, updated_perms):
        """Persist the bot's updated configuration and permissions."""
        self.configloader.save(updated_config)
        self.permsloader.save(updated_perms)
