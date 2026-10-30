"""Write Discord message logs to the drive or database."""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

MESSAGE_LOG_PATH = "message.log.gz"


class Logger:
    """Manage message logging to gzip files and the configured database."""

    def __init__(self, drive, database_obj):
        """Initialize available logging backends and start the message log."""
        self.drive = drive
        self.database = None
        if database_obj.database_connected:
            logger.info("Database connected. Database message logging enabled.")
            self.database = database_obj
        self.logging_enabled = False
        self.msg_log_path = None

        if self.drive.enabled:
            if self.drive.enabled:
                timestamp = (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),)
                with self.drive.gopen(MESSAGE_LOG_PATH, "at") as f:
                    f.write(f"! Logging started at {timestamp}\n")
                self.logging_enabled = True

    async def log_stop(self, *args, **kwargs):
        """Write a timestamped message-log shutdown marker."""
        timestamp = (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),)
        self.log_write(f"! Logging stopped at {timestamp}\n")

    def log_write(self, entry):
        """Append a log entry when file logging is enabled."""
        if not self.logging_enabled:
            return
        with self.drive.gopen(MESSAGE_LOG_PATH, "at") as f:
            f.write(entry)

    def log_message(self, message):
        """Persist a message to the database or append it to the log file."""
        log_entry = "{message.created_at}:{message.channel}:{message.author}:{message.jump_url}:{message.content}\n"
        if self.database is not None and self.database.database_connected:
            self.database.insert_log(message)
        else:
            self.log_write(log_entry)
