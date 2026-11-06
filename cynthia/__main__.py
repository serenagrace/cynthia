"""Command-line entry point for the Cynthia bot."""

import argparse
import os
import subprocess
import sys

from .utils.log import VERBOSE_ENV, get_logger, log_to_file, setup_logging

setup_logging()

from .bot import Bot  # noqa: E402
from .context import Context  # noqa: E402
from .exceptions import ExitCynthia  # noqa: E402
from .utils.auth import verify_factory  # noqa: E402

logger = get_logger(__name__)


def main():
    """Load configuration, start the bot, and handle its shutdown action."""
    parser = argparse.ArgumentParser()
    # parser.add_argument("--uvcgui", action="store_true", help="Enable UVC GUI")
    parser.add_argument("--config", default="config.yaml", help="Override config file")
    parser.add_argument(
        "--perms", default="perms.yaml", help="Override permissions file"
    )
    parser.add_argument("--hunt", type=str, default=None)
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Also log every macro step",
    )

    args = parser.parse_args()
    if args.verbose:
        os.environ[VERBOSE_ENV] = "1"
        setup_logging()

    _context = Context(args)
    log_path = log_to_file(_context.drive_path)
    if log_path is None:
        logger.warning("No drive configured; logging to the console only.")
    else:
        logger.notice(f"Logging to `{log_path}`.")
    sys.excepthook = _log_uncaught
    bot = None
    try:
        bot = Bot(_context)
        if _context.env.DISCORD_BOT_TOKEN is None:
            logger.error("'DISCORD_BOT_TOKEN' not specified in .env file.")
            raise ValueError("Must specify 'DISCORD_BOT_TOKEN' in .env file.")

        if _context.env.OTP_SECRET is None:
            logger.warning(
                "'OTP_SECRET' not specified in .env file. OTP verification will be disabled."
            )
        else:
            bot.verify = verify_factory(_context.env.OTP_SECRET)

        bot.run(_context.env.DISCORD_BOT_TOKEN, log_handler=None)
    except KeyboardInterrupt:
        # Ctrl-C is an expected way to stop the bot, at any point in startup
        pass

    action = _exit_action(bot)
    logger.notice(f"Shutting down ({action or 'interrupted'}).")
    if bot is not None:
        try:
            _context.update_config(bot.config.dict(), bot.perms.dict())
        except KeyboardInterrupt:
            logger.warning("Interrupted while saving config; config not saved.")

    if action == "Restart":
        logger.notice("Restarting...")
        exit(2)
    if action == "Reboot":
        logger.notice("Rebooting host...")
        subprocess.run(["sudo", "-n", "reboot"])
    exit(0)


def _log_uncaught(exc_type, exc, tb):
    """Send a crash's traceback through logging so the log file keeps it."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    logger.critical("Uncaught exception", exc_info=(exc_type, exc, tb))


def _exit_action(bot):
    """Return the ExitCynthia action ("Restart", "Reboot", ...) or None for Ctrl-C."""
    reason = getattr(bot, "kill_reason", None)
    if reason is None:
        return None
    reasons = reason if isinstance(reason, list) else [reason]
    for _, exc, _ in reasons:
        if isinstance(exc, ExitCynthia) and exc.args:
            return exc.args[0]
    return None


if __name__ == "__main__":
    main()
