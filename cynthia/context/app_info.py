"""Collect build and runtime metadata for the bot."""

import subprocess
from datetime import datetime

from cynthia.utils.version import display_version


def get_app_info():
    """Return the project version, Git revision, and build and run timestamps."""
    githash = "??????"
    try:
        githash = (
            subprocess.check_output(["git", "rev-parse", "--short", "HEAD"])
            .decode("ascii")
            .strip()
        )
    except:
        pass
    latest_commit = "???"
    try:
        latest_commit = (
            subprocess.check_output(["git", "log", "-1", "--format=%ct"])
            .decode("ascii")
            .strip()
        )
    except:
        pass
    tstamp = datetime.fromtimestamp(int(latest_commit)).strftime("%Y-%m-%d %H:%M:%S")
    metadata = {
        "version": display_version(),
        "git_hash": githash,
        "git_timestamp": tstamp,
        "run_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    return metadata
