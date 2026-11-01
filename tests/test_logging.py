import logging

import pytest

from cynthia.utils.log import NOISY_LOGGERS, QUIET_OCR_LOGGERS, setup_logging


@pytest.mark.parametrize(
    "name",
    ["discord", "discord.client", "discord.gateway", "discord.http", "discord.state"],
)
def test_discord_logs_start_at_info(monkeypatch, name):
    root = logging.getLogger()
    logger = logging.getLogger(name)
    root_level = root.level
    root_handlers = root.handlers[:]
    logger_names = set(NOISY_LOGGERS) | set(QUIET_OCR_LOGGERS) | {name}
    logger_levels = {n: logging.getLogger(n).level for n in logger_names}
    logger_filters = {n: logging.getLogger(n).filters[:] for n in logger_names}

    for key in (
        "FLAGS_call_stack_level",
        "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK",
        "GLOG_minloglevel",
        "OPENCV_LOG_LEVEL",
        "OPENCV_VIDEOIO_DEBUG",
    ):
        monkeypatch.setenv(key, "")

    try:
        logger.setLevel(logging.NOTSET)
        logging.getLogger("discord").setLevel(logging.NOTSET)
        setup_logging()
        assert not logger.isEnabledFor(logging.DEBUG)
        assert logger.isEnabledFor(logging.INFO)
    finally:
        root.handlers[:] = root_handlers
        root.setLevel(root_level)
        for n, level in logger_levels.items():
            other = logging.getLogger(n)
            other.setLevel(level)
            other.filters[:] = logger_filters[n]
