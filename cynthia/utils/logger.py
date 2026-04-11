import gzip
from datetime import datetime
from pathlib import Path


class Logger:
    def __init__(self, drive_path):
        self.logging_enabled = False
        self.msg_log_path = None

        if drive_path is not None:
            self.msg_log_path = Path(drive_path) / "message_log.gz"
            if self.msg_log_path.parent.exists():
                timestamp = (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),)
                with gzip.open(self.msg_log_path, "at", encoding="utf-8") as f:
                    f.write(f"! Logging started at {timestamp}\n")
                self.logging_enabled = True

    async def log_stop(self, *args, **kwargs):
        timestamp = (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),)
        self.log_write(f"! Logging stopped at {timestamp}\n")

    def log_write(self, entry):
        if not self.logging_enabled:
            return
        with gzip.open(self.msg_log_path, "at", encoding="utf-8") as f:
            f.write(entry)

    def log_message(self, message):
        log_entry = "{message.created_at}:{message.channel}:{message.author}:{message.jump_url}:{message.content}\n"
        self.log_write(log_entry)
