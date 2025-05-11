import discord


class Bot(discord.Client):
    def __init__(self, config):
        self.config = config
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(intents=intents)

    async def on_ready(self):
        await self.change_presence(
            status=discord.Status.online,
            activity=discord.Activity(
                type=discord.ActivityType.watching, name="over the home."
            ),
        )
        msg = "Logged on as", self.user
        print(msg)
        await self.to_owner(msg)

    async def to_owner(self, msg):
        user_owner = await self.fetch_user(self.config.owner)
        await user_owner.send(msg)

    async def on_message(self, message):
        # don't respond to ourselves
        if message.author == self.user:
            return

        if message.content == "ping":
            await message.channel.send("pong")
