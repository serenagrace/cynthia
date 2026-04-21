from datetime import datetime
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

MESSAGE_LOG_PATH = "message.log.gz"


class Logger:
    def __init__(self, drive, database_obj):
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
        timestamp = (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),)
        self.log_write(f"! Logging stopped at {timestamp}\n")

    def log_write(self, entry):
        if not self.logging_enabled:
            return
        with self.drive.gopen(MESSAGE_LOG_PATH, "at") as f:
            f.write(entry)

    def log_message(self, message):
        log_entry = "{message.created_at}:{message.channel}:{message.author}:{message.jump_url}:{message.content}\n"
        if self.database is not None and self.database.database_connected:
            self.database.insert_log(message)
        else:
            self.log_write(log_entry)
