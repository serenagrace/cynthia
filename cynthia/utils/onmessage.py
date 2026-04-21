from pathlib import Path
from cynthia.utils.nxbt_utils import Macro
import pickle

ONMESSAGE = {}


class OnMessage:
    async def default_condition(self, client, message):
        return True

    async def default_action(self, client, message):
        if self.logger is not None:
            self.logger.log_message(message)

    async def nxbt_action(self, client, message):
        nx = getattr(client, "nxbt", None)
        controller = getattr(client, "nxbt_controller", None)

        if nx is None or controller is None:
            return

        macro = Macro(message.content)
        await macro.play(nx, controller)

    def __init__(
        self,
        logger=None,
        type="log",
        condition_type=None,
        action_type=None,
        channel=None,
        guild=None,
    ):
        self.type = type
        self.logger = logger
        self.channel = channel
        self.guild = guild
        self.condition = self.default_condition
        self.condition_type = "default"
        self.action_type = "default"
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


def load_onmessage(client):
    logger = client.logger
    db = client.database
    if not db.database_connected:
        return
    rows = db.get_onmessage()
    for row in rows:
        type, server_id, channel_id, condition_type, action_type = row
        key = f"{type}_{server_id}_{channel_id}"
        ONMESSAGE[key] = OnMessage(
            logger,
            type=type,
            condition_type=condition_type,
            action_type=action_type,
            channel=client.get_channel(channel_id),
            guild=client.get_guild(server_id),
        )


def save_onmessage(db):
    if not db.database_connected:
        return
    db.clear_onmessage()
    for onmessage in ONMESSAGE.values():
        db.insert_onmessage(onmessage)
