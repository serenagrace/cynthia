import logging

from cynthia.utils.log import NOISY_LOGGERS, QUIET_OCR_LOGGERS, setup_logging


def test_discord_gateway_logs_start_at_warning(monkeypatch):
    root = logging.getLogger()
    gateway = logging.getLogger("discord.gateway")
    root_level = root.level
    root_handlers = root.handlers[:]
    logger_names = set(NOISY_LOGGERS) | set(QUIET_OCR_LOGGERS)
    logger_levels = {name: logging.getLogger(name).level for name in logger_names}
    logger_filters = {name: logging.getLogger(name).filters[:] for name in logger_names}
    gateway_level = gateway.level

    for key in (
        "FLAGS_call_stack_level",
        "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK",
        "GLOG_minloglevel",
        "OPENCV_LOG_LEVEL",
        "OPENCV_VIDEOIO_DEBUG",
    ):
        monkeypatch.setenv(key, "")

    try:
        gateway.setLevel(logging.NOTSET)
        setup_logging()
        assert gateway.level == logging.WARNING
    finally:
        root.handlers[:] = root_handlers
        root.setLevel(root_level)
        gateway.setLevel(gateway_level)
        for name, level in logger_levels.items():
            logger = logging.getLogger(name)
            logger.setLevel(level)
            logger.filters[:] = logger_filters[name]
