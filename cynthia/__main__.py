from context import Context
from bot import Bot

_context = Context("config.yaml")

bot = Bot(_context.config)
if _context.env.DISCORD_BOT_TOKEN is None:
    raise ValueError("Must specify 'DISCORD_BOT_TOKEN' in .env file.")

bot.run(_context.env.DISCORD_BOT_TOKEN)
