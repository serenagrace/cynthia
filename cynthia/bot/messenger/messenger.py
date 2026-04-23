import discord
from .response_matrix import ResponseMatrix


class Messenger:
    def __init__(self, bot_obj):
        self.bot = bot_obj

    async def msg_owner(self, msg, *, silent=False, alert=False):
        user_owner = await self.bot.fetch_user(self.bot.config.owner)
        await self.send_msg(user_owner, msg, silent, alert)

    async def send_msg(self, send_context, msg, *, silent=False, alert=False):
        if isinstance(msg, discord.Embed):
            await send_context.send(
                embed=msg, silent=(self.bot.config.silent or silent) and not alert
            )
        else:
            await send_context.send(msg, silent=self.bot.config.silent and silent)

    async def send_list(self, send_context, title, items):
        if not items:
            await send_context.response.send_message(f"{title}\n*(Empty.)*")
            return

        formatted_items = "\n".join(f" - {item}" for item in items)
        await send_context.response.send_message(f"{title}\n{formatted_items}")

    async def respond(self, message):
        # don't respond to ourselves
        if message.author == self.bot.user:
            return

        if message.content in ResponseMatrix:
            await ResponseMatrix[message.content](self, message)
