"""Load environment variables from a file and the process environment."""

import os
from pathlib import Path

import dotenv


class EnvLoader:
    """Read environment values from a dotenv file and process environment."""

    def __init__(self, filename):
        """Create a loader for an existing environment file."""
        if not Path(filename).exists():
            raise FileNotFoundError("Specified environment file does not exist.")
        self.filename = filename

    def __call__(self):
        """Return file values overridden by variables in the process environment."""
        config = {**dotenv.dotenv_values(self.filename), **os.environ}
        return config
