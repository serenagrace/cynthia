"""Read-only, anonymous Twitch chat reader for the chat overlay."""

import asyncio
import logging
import random
import re
import time
from collections import deque

logger = logging.getLogger(__name__)

IRC_HOST = "irc.chat.twitch.tv"
IRC_PORT = 6697
RECONNECT_SECONDS = 10
MAX_MESSAGES = 50
PRIVMSG = re.compile(
    r"^(?:@(?P<tags>\S+) )?:(?P<nick>[^!\s]+)![^\s]* PRIVMSG #\S+ :(?P<text>.*)$"
)


def parse_privmsg(line):
    """Return a message dict for an IRC PRIVMSG line, or None for anything else."""
    match = PRIVMSG.match(line)
    if match is None:
        return None
    tags = dict(
        part.split("=", 1)
        for part in (match.group("tags") or "").split(";")
        if "=" in part
    )
    return {
        "user": tags.get("display-name") or match.group("nick"),
        "color": tags.get("color") or None,
        "text": match.group("text"),
        "time": time.time(),
    }


class TwitchChat:
    """Keep the latest chat messages of one channel, connecting anonymously."""

    def __init__(self, channel):
        """Remember the channel (without `#`) to read."""
        self.channel = channel.lstrip("#").lower()
        self.messages = deque(maxlen=MAX_MESSAGES)

    def recent(self, count=15):
        """Return the newest `count` messages, oldest first."""
        return list(self.messages)[-count:]

    async def run(self):
        """Stay connected, reconnecting after failures, until cancelled."""
        while True:
            try:
                await self._session()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("Twitch chat disconnected: %r", e)
            await asyncio.sleep(RECONNECT_SECONDS)

    async def _session(self):
        """Join the channel and collect messages until the connection drops."""
        reader, writer = await asyncio.open_connection(IRC_HOST, IRC_PORT, ssl=True)
        try:
            nick = f"justinfan{random.randint(10000, 99999)}"
            writer.write(
                f"CAP REQ :twitch.tv/tags\r\nNICK {nick}\r\nJOIN #{self.channel}\r\n".encode()
            )
            await writer.drain()
            while line := await reader.readline():
                text = line.decode(errors="replace").rstrip("\r\n")
                if text.startswith("PING"):
                    writer.write(text.replace("PING", "PONG", 1).encode() + b"\r\n")
                    await writer.drain()
                    continue
                message = parse_privmsg(text)
                if message is not None:
                    self.messages.append(message)
        finally:
            writer.close()
