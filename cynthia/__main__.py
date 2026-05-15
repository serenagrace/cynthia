import argparse
from .context import Context
from .bot import Bot
from .exceptions import *
from .utils.auth import verify_factory
import logging

import sys
from pathlib import Path

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)
logging.getLogger("nxbt").setLevel(logging.INFO)


def main():

    parser = argparse.ArgumentParser()
    # parser.add_argument("--uvcgui", action="store_true", help="Enable UVC GUI")
    parser.add_argument("--config", default="config.yaml", help="Override config file")
    parser.add_argument("--hunt", type=str, default=None)

    args = parser.parse_args()

    _context = Context(args)
    bot = Bot(_context)
    if _context.env.DISCORD_BOT_TOKEN is None:
        logger.error("Error: 'DISCORD_BOT_TOKEN' not specified in .env file.")
        raise ValueError("Must specify 'DISCORD_BOT_TOKEN' in .env file.")

    if _context.env.OTP_SECRET is None:
        logger.warn(
            "Warning: 'OTP_SECRET' not specified in .env file. OTP verification will be disabled."
        )
    else:
        bot.verify = verify_factory(_context.env.OTP_SECRET)

    bot.run(_context.env.DISCORD_BOT_TOKEN)

    print(bot.kill_reason)

    _context.update_config(bot.config.dict())

    if len(bot.kill_reason[1].args) and bot.kill_reason[1].args[0] == "Restart":
        logger.info("Restarting...")
        exit(2)
    exit(0)


if __name__ == "__main__":
    main()
