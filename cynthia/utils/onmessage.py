from cynthia.utils.nxbt_utils import Macro


class OnMessage:
    units = dict()

    async def default_condition(self, client, message):
        return True

    async def default_action(self, client, message):
        if self.logger is not None:
            self.logger.log_message(message)

    async def nxbt_action(self, client, message):
        if hasattr(client, "dman"):
            NXBTDaemon = self.dman.running_daemons.get("NXBTDaemon", None)
            if NXBTDaemon is None:
                return
            if not NXBTDaemon.connected:
                return

            macro = Macro(message.content)
            NXBTDaemon.queue(macro)

    def __init__(
        self,
        logger=None,
        _type="log",
        condition_type=None,
        action_type=None,
        channel=None,
        guild=None,
        persist=True,
    ):
        self.type = _type
        self.logger = logger
        self.channel = channel
        self.guild = guild
        self.condition = self.default_condition
        self.condition_type = "default"
        self.action_type = "default"
        self.persist = persist
        if condition_type is not None:
            self.condition = getattr(
                self, condition_type + "_condition", self.default_condition
            )
        self.action = self.default_action
        self.action_type = "default"
        if action_type is not None:
            self.action = getattr(self, action_type + "_action", self.default_action)

    async def call(self, client, message):
        if self.channel is not None and message.channel.id != self.channel.id:
            return
        if self.guild is not None and message.guild.id != self.guild.id:
            return
        if await self.condition(client, message):
            await self.action(client, message)


async def load_onmessage(client):
    logger = client.logger
    db = client.database
    if not db.database_connected:
        return
    rows = db.get_onmessage()
    for row in rows:
        _type, server_id, channel_id, condition_type, action_type = row
        key = f"{_type}_{server_id}_{channel_id}"
        OnMessage.units[key] = OnMessage(
            logger,
            _type=_type,
            condition_type=condition_type,
            action_type=action_type,
            channel=await client.fetch_channel(channel_id),
            guild=await client.fetch_guild(server_id),
        )


def save_onmessage(db):
    if not db.database_connected:
        return
    for onmessage in OnMessage.units.values():
        if not onmessage.persist:
            continue
        db.insert_onmessage(onmessage)
