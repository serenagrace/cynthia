"""Shared logging setup: one colorized format for every logger.

Wrap object names (modules, daemons, cogs, commands) in backticks in a
message to highlight them; the backticks are not printed when color is on.
Modules keep using ``logging.getLogger(__name__)`` (or ``get_logger(__name__)``);
records propagate to the root handler installed by ``setup_logging``.
"""

import logging
import os
import re
import sys

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
NOTICE = 25
logging.addLevelName(NOTICE, "NOTICE")


def _notice(self, message, *args, **kwargs):
    """Log an important milestone (startup, connections, counts)."""
    if self.isEnabledFor(NOTICE):
        self._log(NOTICE, message, args, **kwargs)


logging.Logger.notice = _notice
LEVEL_COLORS = {
    NOTICE: "\033[1;92m",
    logging.DEBUG: "\033[36m",
    logging.INFO: "\033[32m",
    logging.WARNING: "\033[33m",
    logging.ERROR: "\033[31m",
    logging.CRITICAL: "\033[1;41m",
}
MODULE_COLOR = "\033[1;35m"
OBJECT_COLOR = "\033[1;96m"
OBJECT_RE = re.compile(r"`([^`\n]+)`")
NOISY_LOGGERS = {
    # discord.py logs every gateway event and HTTP request at DEBUG
    "discord": logging.INFO,
    "nxbt": logging.INFO,
    "httpcore": logging.INFO,
    "httpx": logging.INFO,
    "pytesseract": logging.INFO,
    "matplotlib": logging.WARNING,
    "asyncio": logging.WARNING,
    "PIL": logging.WARNING,
}
QUIET_OCR_LOGGERS = ("ppocr", "paddle", "paddlex", "paddleocr", "PIL")


class ColorFormatter(logging.Formatter):
    """Dim timestamp and boilerplate; highlight module name and message."""

    def __init__(self, color=True):
        super().__init__()
        self.color = color

    def format(self, record):
        message = record.getMessage()
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            message = f"{message}\n{record.exc_text}"
        if record.stack_info:
            message = f"{message}\n{self.formatStack(record.stack_info)}"
        time = self.formatTime(record, "%H:%M:%S")
        name = record.name.removeprefix("cynthia.")
        if record.levelno >= logging.WARNING and record.funcName not in (
            "<module>",
            "",
        ):
            name = f"{name}.{record.funcName}"
        level = f"{record.levelname:<8}"
        if not self.color:
            return f"{time} {level} {name}: {message}"
        # `backticked` names are highlighted so objects stand out from prose
        lc = LEVEL_COLORS.get(record.levelno, "")
        if record.levelno == NOTICE:
            style = lc
        elif record.levelno < logging.INFO:
            style = DIM
        elif record.levelno >= logging.WARNING:
            style = lc
        else:
            style = ""
        style_end = RESET + style
        message = OBJECT_RE.sub(
            lambda m: f"{OBJECT_COLOR}{m.group(1)}{style_end}", message
        )
        return (
            f"{DIM}{time}{RESET} {lc}{level}{RESET} "
            f"{MODULE_COLOR}{name}{RESET}{DIM}:{RESET} {style}{message}{RESET}"
        )


class _MinLevel(logging.Filter):
    """Drop records below WARNING."""

    def filter(self, record):
        return record.levelno >= logging.WARNING


def quiet_ocr():
    """Silence PaddleOCR/OpenCV model-load chatter. Call before importing paddleocr."""
    os.environ.setdefault("FLAGS_call_stack_level", "0")
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    os.environ.setdefault("GLOG_minloglevel", "3")
    os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
    os.environ.setdefault("OPENCV_VIDEOIO_DEBUG", "0")
    for name in QUIET_OCR_LOGGERS:
        quiet = logging.getLogger(name)
        quiet.setLevel(logging.ERROR)
        # paddlex re-sets its level and uses its own handler; a filter always wins
        if not any(isinstance(f, _MinLevel) for f in quiet.filters):
            quiet.addFilter(_MinLevel())


def setup_logging(level=logging.DEBUG):
    """Install the colorized root handler (idempotent)."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_cynthia", False):
            root.removeHandler(handler)
    handler = logging.StreamHandler()
    handler._cynthia = True
    handler.setFormatter(
        ColorFormatter(sys.stderr.isatty() and "NO_COLOR" not in os.environ)
    )
    root.addHandler(handler)
    root.setLevel(level)
    for name, lvl in NOISY_LOGGERS.items():
        logging.getLogger(name).setLevel(lvl)
    quiet_ocr()


def get_logger(name, level=None):
    """Return a logger that uses the shared format."""
    logger = logging.getLogger(name)
    if level is not None:
        logger.setLevel(level)
    return logger
