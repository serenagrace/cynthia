from pathlib import Path
import yaml


class ConfigLoader:
    def __init__(self, filename):
        if not Path(filename).exists():
            raise FileNotFoundError("Specified config file does not exist.")
        self.filename = filename

    def __call__(self):
        with open(self.filename, "r") as f:
            config = yaml.load(f, Loader=yaml.Loader)
        return config
