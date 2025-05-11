from .env import EnvLoader
from .config import ConfigLoader
from utils import Namespace


class Context:
    def __init__(self, configfile):
        self.env = Namespace(EnvLoader(".env")())
        self.config = Namespace(ConfigLoader(configfile)())
