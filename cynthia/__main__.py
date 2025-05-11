from context import Context
from bot import Bot

_context = Context("config.yaml")

bot = Bot(_context.config)
print(_context.env.DISCORD_BOT_TOKEN)
bot.run(_context.env.DISCORD_BOT_TOKEN)
