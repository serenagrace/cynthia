import logging
import multiprocessing
import os

import pytest

from cynthia.utils.log import (
    NOISY_LOGGERS,
    QUIET_OCR_LOGGERS,
    VERBOSE_ENV,
    VERBOSE_LOGGERS,
    log_to_file,
    setup_logging,
)


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


@pytest.mark.parametrize("verbose, shown", [("", False), ("1", True)])
def test_macro_steps_reach_the_console_only_when_verbose(monkeypatch, verbose, shown):
    root = logging.getLogger()
    saved = root.level, root.handlers[:]
    monkeypatch.setenv(VERBOSE_ENV, verbose)
    try:
        setup_logging()
        console = next(h for h in root.handlers if getattr(h, "_cynthia", False))
        step = logging.LogRecord(
            f"{VERBOSE_LOGGERS[0]}", logging.DEBUG, "", 0, "Playing A", None, None
        )
        other = logging.LogRecord("cynthia.bot", logging.DEBUG, "", 0, "x", None, None)
        assert logging.getLogger(VERBOSE_LOGGERS[0]).isEnabledFor(logging.DEBUG)
        assert bool(console.filter(step)) is shown
        assert console.filter(other)
    finally:
        root.setLevel(saved[0])
        root.handlers[:] = saved[1]


def test_log_file_is_shared_with_forked_daemons_and_rotated_by_the_owner(tmp_path):
    root = logging.getLogger()
    saved = root.level, root.handlers[:]
    logger = logging.getLogger("cynthia.test_log_file")
    try:
        assert log_to_file(tmp_path / "missing") is None
        path = log_to_file(str(tmp_path), max_bytes=400, backups=2)
        root.setLevel(logging.DEBUG)
        logger.debug("from the bot")

        def child():
            logger.debug("from a daemon")
            raise SystemExit(0)

        process = multiprocessing.get_context("fork").Process(target=child)
        process.start()
        process.join(10)
        assert process.exitcode == 0
        text = open(path).read()
        assert "DEBUG    test_log_file: from the bot" in text
        assert "from a daemon" in text
        assert text[:4].isdigit() and text[4] == "-"

        for index in range(40):
            logger.info(f"line {index}")
        for index in range(1, 3):
            assert os.path.exists(f"{path}.{index}")
        assert not os.path.exists(f"{path}.3")
        assert "line 39" in open(path).read()
    finally:
        for handler in root.handlers:
            if getattr(handler, "_cynthia_file", False):
                handler.close()
        root.setLevel(saved[0])
        root.handlers[:] = saved[1]


def _crash():
    raise RuntimeError("capture exploded")


def test_daemon_crash_is_logged(caplog):
    import signal

    from cynthia.daemons.daemon import _run_loop

    sigint = signal.getsignal(signal.SIGINT)
    try:
        with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exit_info:
            _run_loop(_crash, ())
    finally:
        signal.signal(signal.SIGINT, sigint)
    assert exit_info.value.code == 1
    assert "_crash` crashed" in caplog.text
    assert "capture exploded" in caplog.text
