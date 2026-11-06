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
# Moderation: CLEARMSG deletes one message, CLEARCHAT a user's (ban/timeout) or all
CLEAR = re.compile(
    r"^(?:@(?P<tags>\S+) )?:\S+ (?P<command>CLEARMSG|CLEARCHAT) #\S+(?: :(?P<target>.*))?$"
)
# Fields the overlay shows; the rest only match moderation events
PUBLIC_FIELDS = ("user", "color", "text", "time")


def pane_messages(state):
    """Return visible pane messages, excluding local removals from shared state."""
    cleared = getattr(state, "twitch_chat_cleared_at", 0)
    users = getattr(state, "twitch_chat_user_clears", {})
    hidden = set(getattr(state, "twitch_chat_hidden_ids", []))
    return [
        message
        for message in getattr(state, "twitch_chat_messages", [])
        if message["time"] > cleared
        and message["time"] > users.get(message["login"], 0)
        and message["id"] not in hidden
    ][-15:]


def clear_pane(state, *, message_id=None, login=None):
    """Hide one message, a user's existing messages, or all existing pane chat."""
    messages = getattr(state, "twitch_chat_messages", [])
    if message_id is not None:
        active = {message["id"] for message in messages}
        hidden = set(getattr(state, "twitch_chat_hidden_ids", [])) & active
        hidden.add(message_id)
        state.twitch_chat_hidden_ids = list(hidden)
    elif login is not None:
        active = {message["login"] for message in messages}
        users = {
            user: cutoff
            for user, cutoff in getattr(state, "twitch_chat_user_clears", {}).items()
            if user in active
        }
        users[login] = time.time()
        state.twitch_chat_user_clears = users
    else:
        state.twitch_chat_cleared_at = time.time()


def parse_tags(tags):
    """Split an IRCv3 tag string into a dict."""
    return dict(part.split("=", 1) for part in (tags or "").split(";") if "=" in part)


def parse_privmsg(line):
    """Return a message dict for an IRC PRIVMSG line, or None for anything else."""
    match = PRIVMSG.match(line)
    if match is None:
        return None
    tags = parse_tags(match.group("tags"))
    return {
        "user": tags.get("display-name") or match.group("nick"),
        "color": tags.get("color") or None,
        "text": match.group("text"),
        "time": time.time(),
        "id": tags.get("id"),
        "login": match.group("nick").lower(),
        "user_id": tags.get("user-id"),
        # login of the chatter this message replies to, if it's a reply
        "reply_to": (tags.get("reply-parent-user-login") or "").lower() or None,
    }


class TwitchChat:
    """Keep the latest chat messages of one channel, connecting anonymously."""

    def __init__(self, channel, listener=None):
        """Remember the channel (without `#`) to read.

        `listener(kind, data)`, if given, hears each `"message"` (the message
        dict) and `"delete"` (`{"id"}`, `{"login", "user_id"}`, or `{}` for a
        full clear).
        """
        self.channel = channel.lstrip("#").lower()
        self.messages = deque(maxlen=MAX_MESSAGES)
        self.listener = listener

    def notify(self, kind, data):
        """Tell the listener about a chat event without letting it break reading."""
        if self.listener is None:
            return
        try:
            self.listener(kind, data)
        except Exception:
            logger.exception("Twitch chat listener failed.")

    def recent(self, count=15):
        """Return the newest `count` messages, oldest first."""
        return [
            {key: message[key] for key in PUBLIC_FIELDS}
            for message in list(self.messages)[-count:]
        ]

    def handle(self, line):
        """Record a chat message or apply a moderator's deletion."""
        message = parse_privmsg(line)
        if message is not None:
            self.messages.append(message)
            self.notify("message", message)
            return
        match = CLEAR.match(line)
        if match is None:
            return
        tags = parse_tags(match.group("tags"))
        if match.group("command") == "CLEARMSG":
            target = tags.get("target-msg-id")
            self.notify("delete", {"id": target})

            def deleted(m):
                """Match the single message removed by its IRC message ID."""
                return target is not None and m["id"] == target

        elif match.group("target"):
            user_id = tags.get("target-user-id")
            login = match.group("target").strip().lower()
            self.notify("delete", {"login": login, "user_id": user_id})

            def deleted(m):
                """Match messages from the banned or timed-out user."""
                if user_id and m["user_id"]:
                    return m["user_id"] == user_id
                return m["login"] == login

        else:
            self.messages.clear()
            self.notify("delete", {})
            return
        kept = [m for m in self.messages if not deleted(m)]
        self.messages.clear()
        self.messages.extend(kept)

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
                f"CAP REQ :twitch.tv/tags twitch.tv/commands\r\nNICK {nick}\r\nJOIN #{self.channel}\r\n".encode()
            )
            await writer.drain()
            while line := await reader.readline():
                text = line.decode(errors="replace").rstrip("\r\n")
                if text.startswith("PING"):
                    writer.write(text.replace("PING", "PONG", 1).encode() + b"\r\n")
                    await writer.drain()
                    continue
                self.handle(text)
        finally:
            writer.close()
