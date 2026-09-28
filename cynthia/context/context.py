from .env import EnvLoader
from .config import ConfigLoader
from .perms import PermsLoader
from .app_info import get_app_info
from cynthia.utils import Namespace


class Context:
    def __init__(self, args):
        self.configloader = ConfigLoader(args.config)
        self.permsloader = PermsLoader(args.perms)
        self.env = Namespace(EnvLoader(".env")())
        self.config = Namespace(self.configloader())
        self.perms = Namespace(PermsLoader.default())
        self.app_meta = Namespace(get_app_info())
        self.args = Namespace(vars(args))

    def update_config(self, updated_config, updated_perms):
        self.configloader.save(updated_config)
        self.permsloader.save(updated_perms)
