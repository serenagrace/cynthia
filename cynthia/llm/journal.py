"""Append-only record of Twitch chat and how the chat model handled it.

One JSON object per line in `chat_journal/YYYY-MM-DD.jsonl` on the drive: each
chat message with the reply decision (kind, odds, roll or skip reason) and,
when answered, the exact prompt, every draft (blocked ones too) and the reply.
"""

import json
import logging
import time

logger = logging.getLogger(__name__)

FOLDER = "chat_journal"


class Journal:
    """Write journal entries under `drive`; does nothing without a drive."""

    def __init__(self, drive):
        """Keep the drive; files and the folder are made on first write."""
        self.drive = drive

    def path(self, at):
        """The day file for timestamp `at` (local time), or None without a drive."""
        if self.drive is None or not getattr(self.drive, "enabled", False):
            return None
        day = time.strftime("%Y-%m-%d", time.localtime(at))
        return self.drive.path(f"{FOLDER}/{day}.jsonl")

    def write(self, entry):
        """Append `entry` (a dict with a `time`); never raises."""
        try:
            path = self.path(entry.setdefault("time", time.time()))
            if path is None:
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(entry, ensure_ascii=False, default=str)
            with open(path, "a", encoding="utf-8") as file:
                file.write(line + "\n")
        except Exception:
            logger.warning("Couldn't write the chat journal.", exc_info=True)
