import gzip
from pathlib import Path


class Drive:
    def __init__(self, drive_path):
        self.drive_path = None
        self.enabled = False
        if drive_path is None:
            return
        self.drive_path = Path(drive_path)
        self.enabled = self.drive_path.exists() and self.drive_path.is_dir()

    def exists(self, file_path, *, is_file=False, is_dir=False):
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
        if not self.enabled:
            return None
        return self.drive_path / file_path

    def open(self, file_path, mode):
        return open(self.drive_path / file_path, mode)

    def gopen(self, file_path, mode, *, encoding="utf-8"):
        return gzip.open(self.drive_path / file_path, mode, encoding=encoding)

    def touch(self, file_path):
        if not self.enabled:
            return None
        path = self.drive_path / file_path
        path.touch()

        return path
