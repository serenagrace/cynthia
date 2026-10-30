"""Filesystem access helpers for the configured bot drive."""

import gzip
from pathlib import Path


class Drive:
    """Access files under an optional configured drive directory."""

    def __init__(self, drive_path):
        """Enable drive access only when the configured path is a directory."""
        self.drive_path = None
        self.enabled = False
        if drive_path is None:
            return
        self.drive_path = Path(drive_path)
        self.enabled = self.drive_path.exists() and self.drive_path.is_dir()

    def exists(self, file_path, *, is_file=False, is_dir=False):
        """Check whether a drive path exists and matches optional type checks."""
        if not self.enabled:
            return False

        file_path = self.drive_path / file_path

        if not file_path.exists():
            return False

        if is_file and not file_path.is_file():
            return False

        if is_dir and not file_path.is_dir():
            return False

        return True

    def path(self, file_path):
        """Return the drive path, or None when drive access is disabled."""
        if not self.enabled:
            return None
        return self.drive_path / file_path

    def open(self, file_path, mode, touch=False):
        """Open a drive file, optionally creating it first."""
        if touch:
            self.touch(file_path)
        return open(self.drive_path / file_path, mode)

    def gopen(self, file_path, mode, *, encoding="utf-8"):
        """Open a gzip-compressed file under the drive directory."""
        return gzip.open(self.drive_path / file_path, mode, encoding=encoding)

    def touch(self, file_path):
        """Create a drive file if needed and return its path."""
        if not self.enabled:
            return None
        path = self.drive_path / file_path
        path.touch()

        return path
