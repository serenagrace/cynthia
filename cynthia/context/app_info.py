import subprocess
from datetime import datetime


def get_app_info():
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
        "git_hash": githash,
        "git_timestamp": tstamp,
        "run_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    return metadata
