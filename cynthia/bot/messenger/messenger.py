from .response_matrix import ResponseMatrix


class Messenger:
    def __init__(self, bot_obj):
        self.bot = bot_obj

    async def msg_owner(self, msg):
        user_owner = await self.bot.fetch_user(self.bot.config.owner)
        await self.send_msg(user_owner, msg)

    async def send_msg(self, send_context, msg):
        await send_context.send(msg, silent=self.bot.config.silent)

    async def respond(self, message):
        # don't respond to ourselves
        if message.author == self.bot.user:
            return

        if message.content in ResponseMatrix:
            await ResponseMatrix[message.content](self, message)
