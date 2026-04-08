class OnMessage:
    def __init__(self, client, condition=None, action=None, channel=None, guild=None):
        self.client = client
        self.channel = channel
        self.guild = guild

        async def default_condition(message):
            return True

        async def default_action(message):
            self.client.log_message(message)

        self.condition = condition or default_condition
        self.action = action or default_action

    async def __call__(self, message):
        if self.channel is not None and message.channel.id != self.channel:
            return
        if self.guild is not None and message.guild.id != self.guild:
            return
        if await self.condition(message):
            await self.action(self.client, message)
