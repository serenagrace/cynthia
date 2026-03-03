from context import Context
from bot import Bot
from .exceptions import *
from utils.auth import verify_factory

import sys
from pathlib import Path

_exit = False

while not _exit:
    _exit = True
    _context = Context("config.yaml")

    bot = Bot(_context)
    if _context.env.DISCORD_BOT_TOKEN is None:
        raise ValueError("Must specify 'DISCORD_BOT_TOKEN' in .env file.")

    if _context.env.OTP_SECRET is None:
        print(
            "Warning: 'OTP_SECRET' not specified in .env file. OTP verification will be disabled."
        )
    else:
        bot.verify = verify_factory(_context.env.OTP_SECRET)

    bot.run(_context.env.DISCORD_BOT_TOKEN)

    print(bot.kill_reason)

    try:
        if bot.kill_reason[1].args[0] == "Restart":
            _exit = False
    except:
        pass
