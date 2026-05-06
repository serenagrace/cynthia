from .env import EnvLoader
from .config import ConfigLoader
from .app_info import get_app_info
from cynthia.utils import Namespace


class Context:
    def __init__(self, args):
        self.configloader = ConfigLoader(args.config)
        self.env = Namespace(EnvLoader(".env")())
        self.config = Namespace(self.configloader())
        self.app_meta = Namespace(get_app_info())
        self.args = Namespace(vars(args))

    def update_config(self, updated_config):
        self.configloader.save(updated_config)
