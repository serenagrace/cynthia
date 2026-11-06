"""Running version, marked alpha when the code isn't a released (master) build."""

import functools
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RELEASE_REF = "origin/master"
# Changes here alter what runs; edits to tests or docs don't
CODE_PATHS = ("cynthia", "pyproject.toml")
ALPHA = "alpha"


def _git(repo, *args):
    """Run git in `repo`; safe.directory lets root (sudo) read a user's checkout."""
    return subprocess.run(
        ["git", "-c", f"safe.directory={repo}", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=5,
    )


def is_alpha(repo=REPO, release_ref=RELEASE_REF):
    """Whether `repo` runs uncommitted code or commits not on `release_ref`.

    Not a git checkout (a normal install) or git failing counts as released.
    """
    if not (Path(repo) / ".git").exists():
        return False
    try:
        status = _git(repo, "status", "--porcelain", "--", *CODE_PATHS)
        if status.returncode != 0:
            return False
        if status.stdout.strip():
            return True
        # Exit 0: HEAD is in the release branch, 1: it isn't, else: no such ref
        released = _git(repo, "merge-base", "--is-ancestor", "HEAD", release_ref)
        return released.returncode == 1
    except (OSError, subprocess.SubprocessError):
        return False


@functools.cache
def running_alpha():
    """`is_alpha()` for this checkout, checked once: it describes the code loaded."""
    return is_alpha()


def display_version():
    """The installed version, e.g. `1.8.0`, or `1.8.0-alpha` for unreleased code."""
    try:
        base = version("cynthia")
    except PackageNotFoundError:
        return "dev"
    return f"{base}-{ALPHA}" if running_alpha() else base
