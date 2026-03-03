from .env import EnvLoader
from .config import ConfigLoader
from .app_info import get_app_info
from cynthia.utils import Namespace


class Context:
    def __init__(self, configfile):
        self.env = Namespace(EnvLoader(".env")())
        self.config = Namespace(ConfigLoader(configfile)())
        self.app_meta = Namespace(get_app_info())
