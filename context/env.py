import dotenv
import os
from pathlib import Path


class EnvLoader:
    def __init__(self, filename):
        if not Path(filename).exists():
            raise FileNotFoundError("Specified environment file does not exist.")
        self.filename = filename

    def __call__(self):
        config = {**dotenv.dotenv_values(self.filename), **os.environ}
        return config
