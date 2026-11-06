"""Let the local chat model read Twitch chat, learn about chatters, and talk.

Listening stores every chat message and keeps the recent-chat buffer; learning
turns stored messages into per-chatter notes; speaking posts replies in chat
and the voice reads them on stream; owner DM talk is a plain conversation.
Each is switched with `/llm switch` and saved in the config (`llm_listen`,
`llm_learn`, `llm_speak`, `llm_events`, `llm_voice`, `llm_owner_talk`); `llm_enabled` turns
them all off at once.
"""

import asyncio
import logging
import time
from collections import deque

from discord.ext import commands, tasks

from cynthia.llm.client import LLMClient, LLMError, clean_reply, flag, setting
from cynthia.llm.journal import Journal
from cynthia.llm.memory import Memory, tone
from cynthia.llm.moderation import Moderator, explain
from cynthia.llm.nicknames import MIN_USES as NICKNAME_USES
from cynthia.llm.nicknames import candidates, garbled
from cynthia.llm.pokedex import facts
from cynthia.llm.prompt import (
    event_messages,
    fit,
    is_streamer,
    limit,
    memory_lines,
    mentioned,
    present_names,
    reply_messages,
    reply_problem,
)
from cynthia.llm.pronouns import name_index, referenced, stated
from cynthia.llm.repetition import loops, repeats, similar
from cynthia.llm.state import StateReader, render, stream_start
from cynthia.llm.teach import Teacher, lesson_lines
from cynthia.llm.triggers import (
    Triggers,
    aside,
    bot_names,
    classify,
    heard,
    ignored,
    names_list,
)
from cynthia.llm.voice import Speaker, Voice
from cynthia.utils.twitchapi import MAX_CHAT
from cynthia.utils.twitchchat import TwitchChat

logger = logging.getLogger(__name__)

EVENT_SECONDS = 2
MEMORY_SECONDS = 60
STATE_MAX_AGE = 5
# Without a known stream start, a chatter's "this stream" history goes back this far
HISTORY_FALLBACK_SECONDS = 6 * 3600
# Least time between two counted kind/rude messages from one chatter
TONE_GAP_SECONDS = 600
# Event priority when several happen between checks
EVENT_ORDER = ("shiny", "watchdog", "failsafe", "encounter")
COUNTERS = {
    "encounter": "encounter_count",
    "watchdog": "watchdog_count",
    "failsafe": "failsafe_count",
}
TOGGLES = {
    "all": ("llm_enabled", True),
    "listen": ("llm_listen", True),
    "learn": ("llm_learn", True),
    "speak": ("llm_speak", False),
    "events": ("llm_events", False),
    "voice": ("llm_voice", False),
    "talk": ("llm_owner_talk", False),
}
# Discord's message limit
DISCORD_LIMIT = 2000


def chat_message(user, text, login=None):
    """A chat message dict like the ones Twitch chat produces."""
    return {
        "id": None,
        "time": time.time(),
        "user": user,
        "login": (login or user).lower(),
        "user_id": None,
        "text": text,
        "color": None,
    }


# Tokens kept free beyond the reply for the chat template and estimate error
PROMPT_MARGIN = 64
# Tries at a reply before giving up when filters keep rejecting it
ATTEMPTS = 3
# Blocks that are about how she talks, not safety; logged without a DM
QUIET_REASONS = {"name", "third person", "made up", "doubt"}


def echo_key(text):
    """Text of a chat post as Twitch echoes it: cut to length, spacing collapsed."""
    return " ".join(text[:MAX_CHAT].split()).casefold()


class LLMChatCog(commands.Cog):
    """Read chat, keep context and memories, and reply when triggered."""

    def __init__(self, bot):
        """Build the model client, moderation, state reader and voice."""
        self.bot = bot
        config = bot.config
        self.client = LLMClient(config)
        self.moderator = Moderator(
            allow=names_list(config, "llm_allowed_words", []),
            block=names_list(config, "llm_blocked_words", []),
        )
        self.reader = StateReader(bot)
        self.triggers = Triggers(config)
        self.memory = Memory(
            config, bot.database, self.client, self.moderator, self.blocked
        )
        self.teacher = Teacher(config, bot.database, self.client)
        self.voice = Voice(config)
        self.speaker = None
        self.recent = deque(maxlen=50)
        self.sandbox = deque(maxlen=30)
        self.decisions = deque(maxlen=30)
        # Our own posts, to recognize when chat echoes them back
        self.sent = deque(maxlen=20)
        self.sent_ids = deque(maxlen=50)
        self.toned = {}
        self.names_cached = (float("-inf"), {})
        self.journal = Journal(getattr(bot, "drive", None))
        self.speaking = set()
        self.queue = asyncio.Queue(maxsize=500)
        self.chat = None
        self.chat_task = None
        self.worker_task = None
        self.cached = (0.0, None)
        self.counters = None
        self.last_activity = time.monotonic()
        self.last_notice = 0.0
        self.unnoticed = 0
        # What the bot said lately, for the repetition filter
        self.said = deque(maxlen=50)

    # -- toggles -------------------------------------------------------------

    def enabled(self, name):
        """Whether a switch (see `TOGGLES`) is on; `all` off turns every one off."""
        if name != "all" and not self.enabled("all"):
            return False
        key, default = TOGGLES[name]
        return flag(self.bot.config, key, default)

    def set_enabled(self, name, on):
        """Flip a switch and apply it now; each keeps its own setting under `all`."""
        self.bot.config.set(TOGGLES[name][0], bool(on))
        if name in ("all", "listen"):
            self.sync_listening()

    @property
    def channel(self):
        """The Twitch channel to read."""
        return (self.bot.env.get("TWITCH_CHANNEL", None) or "").strip().lstrip("#")

    def own_names(self):
        """Logins chat may use for the bot: the account it posts as.

        That is the channel itself only while the bot posts as the broadcaster;
        with a bot account, talking to the streamer isn't talking to the bot.
        """
        api = self.chat_api
        return [((api.login if api else None) or self.channel).lower()]

    @property
    def twitch_api(self):
        """The Helix client, once the Twitch cog has made one."""
        return getattr(self.bot, "twitch_api", None)

    @property
    def chat_api(self):
        """Use the separate bot account once set up, otherwise the broadcaster.

        A bot account whose authorization lapsed is still used, so posting fails
        until `/twitch botauth` instead of speaking as the broadcaster.
        """
        api = getattr(self.bot, "twitch_chat_api", None)
        if api is not None and (api.authorized or api.login):
            return api
        return self.twitch_api

    def note(self, text):
        """Remember a decision for `/llm log`."""
        self.decisions.append((time.time(), text))
        logger.debug(text)

    # -- lifecycle -----------------------------------------------------------

    async def cog_load(self):
        """Start reading chat and watching for events."""
        self.worker_task = asyncio.create_task(self.worker())
        self.sync_listening()
        self.watch_events.start()
        self.learn_memories.start()

    async def cog_unload(self):
        """Stop every background task."""
        self.watch_events.cancel()
        self.learn_memories.cancel()
        for task in (self.chat_task, self.worker_task):
            if task is not None:
                task.cancel()
        self.chat_task = None

    def sync_listening(self):
        """Run the chat reader exactly when listening is on and a channel is set."""
        running = self.chat_task is not None and not self.chat_task.done()
        want = self.enabled("listen") and bool(self.channel)
        if want and not running:
            self.chat = TwitchChat(self.channel, listener=self.heard)
            self.chat_task = asyncio.create_task(self.chat.run())
            logger.info("Chat model is listening to #%s.", self.channel)
        elif not want and running:
            self.chat_task.cancel()
            self.chat_task = None
            logger.info("Chat model stopped listening.")

    def heard(self, kind, data):
        """Queue a chat event from the reader for the worker."""
        try:
            self.queue.put_nowait((kind, data))
        except asyncio.QueueFull:
            logger.warning("Chat model is behind; dropped a chat event.")

    async def worker(self):
        """Handle queued chat events one at a time."""
        while True:
            kind, data = await self.queue.get()
            try:
                if kind == "message":
                    await self.on_chat(data)
                else:
                    await self.on_delete(data)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Chat model failed to handle a chat %s.", kind)

    # -- state ---------------------------------------------------------------

    async def state(self, max_age=STATE_MAX_AGE):
        """A recent state snapshot, refreshed when older than `max_age` seconds."""
        at, snapshot = self.cached
        if snapshot is None or time.monotonic() - at > max_age:
            snapshot = await self.reader.snapshot()
            self.cached = (time.monotonic(), snapshot)
        return snapshot

    async def may_talk(self):
        """Whether replies go anywhere: an output is on and the stream is live."""
        if not (self.enabled("speak") or self.enabled("voice")):
            return False
        if flag(self.bot.config, "llm_speak_offline", False):
            return True
        return bool((await self.state())["stream"]["live"])

    # -- chat ----------------------------------------------------------------

    def own_echo(self, message):
        """Whether `message` is one of the bot's own posts coming back from chat.

        Everything from a dedicated bot account is the bot's. When it posts as
        the broadcaster, who also chats, a post is recognized by its message ID
        or, if chat echoes it before Twitch confirms it, by its text.
        """
        api = self.chat_api
        posting = ((api.login if api else None) or "").lower()
        if not posting or message["login"] != posting:
            return False
        if posting != self.channel.lower():
            return True
        by_id = bool(message.get("id")) and message["id"] in self.sent_ids
        text = echo_key(message["text"])
        by_text = text in self.sent
        if by_id:
            self.sent_ids.remove(message["id"])
        if by_text:
            self.sent.remove(text)
        return by_id or by_text

    async def on_chat(self, message):
        """Moderate, store and remember a message, then maybe answer it.

        Every message read, and what was done with it, goes in the journal.
        """
        entry = {
            "type": "chat",
            "time": message.get("time"),
            "id": message.get("id"),
            "user": message.get("user"),
            "login": message["login"],
            "text": message["text"],
            "reply_to": message.get("reply_to"),
        }
        try:
            await self.handle_chat(message, entry)
        finally:
            await asyncio.to_thread(self.journal.write, entry)

    async def handle_chat(self, message, entry):
        """`on_chat`'s work; notes the outcome in the journal `entry`."""
        login = message["login"]
        if ignored(self.bot.config, login):
            entry["skip"] = "ignored chatter"
            return
        if self.own_echo(message):
            entry["type"] = "own post"
            return
        reason = await asyncio.to_thread(self.moderator.check, message["text"])
        message["flagged"] = entry["flagged"] = reason
        state = await self.state(60)
        await asyncio.to_thread(
            self.bot.database.add_chat_message, message, stream_start(state)
        )
        self.last_activity = time.monotonic()
        if aside(message["text"]):
            # (Parenthesized) chat is between people; she doesn't hear it
            entry["skip"] = "aside"
            return
        said = message["text"]
        # She hears a message without its (parenthesized) parts
        message["text"] = heard(said)
        await self.count_tone(message)
        # The streamer is trusted; a flagged word shouldn't hide her from chat
        if reason and not is_streamer(message, self.channel):
            self.note(f"Flagged {message['user']} ({reason}).")
            entry["skip"] = "flagged"
            return
        # "ash (he/him)": pronouns are the one thing read from asides
        entry["pronouns"] = await self.note_pronouns({**message, "text": said})
        prior = list(self.recent)
        self.recent.append(message)
        threshold = float(setting(self.bot.config, "llm_repeat_similarity", 0.8))
        # Only repeating what she already answered counts; asking again after
        # being ignored shouldn't make an answer less likely
        answered = [m["text"] for m in prior if m.get("answered")]
        echoes = repeats(message["text"], answered, threshold)
        kind = self.triggers.message(
            login,
            message["text"],
            echoes,
            self.own_names(),
            message.get("reply_to"),
            streamer=self.channel,
        )
        entry["decision"] = dict(self.triggers.decision, repeats=echoes)
        entry["nicknames"] = await self.note_nicknames(message)
        if echoes:
            self.note(f"{message['user']} repeated answered chat ({echoes}x).")
        if kind is None:
            return
        if not await self.may_talk():
            entry["decision"]["skip"] = "outputs off or not live"
            return
        self.note(f"Answering {message['user']} ({kind}).")
        result = await self.reply_to(message, prior)
        entry.update(
            prompt=result["messages"],
            drafts=(result["data"] or {}).get("drafts", []),
            reply=result["reply"],
            dropped=result["dropped"],
        )
        if result["reply"]:
            # A reply to someone talking to her waits out her pause, not skips
            await asyncio.sleep(self.triggers.wait())
            entry["posted"] = await self.deliver(
                result["reply"], reply_to=message["id"], login=login
            )
            if entry["posted"] is not False:
                message["answered"] = True

    async def known_names(self):
        """Names chat uses for known chatters (see `name_index`), cached a minute."""
        if time.monotonic() - self.names_cached[0] > 60:
            names = await asyncio.to_thread(self.bot.database.chatter_names)
            self.names_cached = (time.monotonic(), name_index(names))
        return self.names_cached[1]

    async def note_nicknames(self, message):
        """Count words in `message` that look like nicknames for present chatters."""
        login = message["login"]
        bots = {*bot_names(self.bot.config), *self.own_names()}
        present = [n for n in self.triggers.seen if n != login and n not in bots]
        if not present:
            return []
        names = await self.known_names()
        found = candidates(message["text"], login, present, [*names, *names.values()])
        for nickname, who in found:
            uses = await asyncio.to_thread(
                self.bot.database.add_nickname_use, who, nickname, message.get("time")
            )
            if uses == NICKNAME_USES:
                self.note(f"New nickname: {nickname} for {who}.")
                self.names_cached = (float("-inf"), {})
        return [{"nickname": n, "login": who} for n, who in found]

    async def note_pronouns(self, message):
        """Keep a message that shows someone's pronouns; returns what it showed.

        Only fixed patterns count: a chatter stating their pronouns, or a
        message clearly about one other chatter (see `pronouns.referenced`).
        """
        login, text = message["login"], message["text"]
        own = stated(text)
        if own:
            found = (login, own, "self")
        else:
            names = await self.known_names()
            bots = [*bot_names(self.bot.config), *self.own_names()]
            ref = referenced(text, login, names, bots)
            if ref is None:
                return None
            found = (*ref, "reference")
        await asyncio.to_thread(
            self.bot.database.add_pronoun_evidence,
            found[0],
            found[1],
            found[2],
            login,
            text,
            message.get("time"),
        )
        self.note(f"Pronoun evidence: {found[0]} {found[1]} ({found[2]}).")
        return {"login": found[0], "pronouns": found[1], "kind": found[2]}

    async def count_tone(self, message):
        """Count a kind or rude message aimed at the bot, rarely enough to drift.

        Only mentions and replies to the bot count, and each chatter at most
        once per `TONE_GAP_SECONDS`, so one outburst barely moves it.
        """
        login = message["login"]
        aimed = classify(
            self.bot.config, message["text"], self.own_names(), message.get("reply_to")
        )
        found = tone(message["text"]) if aimed == "mention" else None
        now = time.monotonic()
        if found is None or now - self.toned.get(login, -TONE_GAP_SECONDS) < (
            TONE_GAP_SECONDS
        ):
            return
        self.toned[login] = now
        await asyncio.to_thread(self.bot.database.count_tone, login, found)

    async def on_delete(self, data):
        """Forget messages a moderator deleted, in the buffer and the database."""
        if not data:
            self.recent.clear()
        elif data.get("id"):
            kept = [m for m in self.recent if m["id"] != data["id"]]
            self.recent = deque(kept, maxlen=self.recent.maxlen)
        else:
            kept = [m for m in self.recent if m["login"] != data.get("login")]
            self.recent = deque(kept, maxlen=self.recent.maxlen)
        if data:
            await asyncio.to_thread(
                self.bot.database.delete_chat_messages,
                data.get("id"),
                data.get("login"),
                data.get("user_id"),
            )

    async def context(self, message, prior):
        """Everything the model sees to answer `message`, as prompt parts."""
        config = self.bot.config
        database = self.bot.database
        state = await self.state()
        recent = prior[-limit(config, "llm_context_messages", 8) :]
        login = message["login"]
        since = stream_start(state) or time.time() - HISTORY_FALLBACK_SECONDS
        history = await asyncio.to_thread(
            database.chat_messages,
            login,
            since,
            limit(config, "llm_user_history", 8) + 1,
        )
        history = [m for m in history if m["id"] != message["id"] or not m["id"]]
        history = [m for m in history if m["text"] != message["text"]]
        history = [{**m, "text": heard(m["text"])} for m in history]
        history = [m for m in history if m["text"]]
        names = await asyncio.to_thread(database.chatter_names)
        others = mentioned(
            message["text"],
            names,
            exclude=[login],
            count=limit(config, "llm_mentioned_memories", 3),
        )
        rows = await asyncio.to_thread(database.chatters, [login, *others])
        return {
            "lessons": await self.guidance(),
            "state": state,
            "lines": render(state),
            "recent": recent,
            "history": history[-limit(config, "llm_user_history", 8) :],
            "memories": memory_lines(rows, self.channel),
            "present": present_names(recent, login, config),
            "mentioned": others,
            "facts": self.pokedex(
                state, [m["text"] for m in recent[-3:]] + [message["text"]]
            ),
        }

    def pokedex(self, state, texts=()):
        """Pokémon facts for the game, hunt target and what chat just said."""
        return facts(
            texts,
            state["game"]["title"],
            state["hunt"]["target"],
            limit(self.bot.config, "llm_pokedex_facts", 6),
        )

    async def guidance(self):
        """Lessons from the owner, plus recent mistakes the filters caught."""
        lines = lesson_lines(await self.teacher.lessons())
        hours = float(setting(self.bot.config, "llm_mistake_hours", 24))
        rows = await asyncio.to_thread(
            self.bot.database.filtered, time.time() - hours * 3600, 50
        )
        reasons = []
        for row in rows:
            if row["reason"] not in reasons:
                reasons.append(row["reason"])
        if reasons:
            lines.append("Mistakes you made recently that got blocked; avoid them:")
            lines += [
                f"- A message was blocked because {explain(reason)}."
                for reason in reasons[:3]
            ]
        return lines

    def repeated(self, reply):
        """Why `reply` repeats itself or something said lately, or None.

        Phrase loops are always rejected; a reply close to `n` recent ones is
        let through with chance `llm_repeat_allow_chance ** n`.
        """
        config = self.bot.config
        if loops(reply):
            return "it kept repeating the same phrase", None
        threshold = float(setting(config, "llm_repeat_similarity", 0.8))
        count = repeats(reply, self.said, threshold)
        if not count:
            return None, None
        allow = float(setting(config, "llm_repeat_allow_chance", 0.2)) ** count
        if self.triggers.rng.random() < allow:
            return None, None
        earlier = similar(reply, self.said, threshold)
        return (
            f'it was nearly the same as something you said lately: "{earlier}"',
            earlier,
        )

    async def check_reply(self, reply, target=None, recent=()):
        """`(reason, explanation)` if a reply can't be sent, else `(None, None)`.

        With the `target` message being answered (and the `recent` chat before
        it), it also checks how the reply treats them and the streamer.
        """
        reason = await asyncio.to_thread(self.moderator.check, reply, True)
        if reason:
            return reason, explain(reason)
        why, _ = self.repeated(reply)
        if why:
            return "repetition", why
        names = await self.known_names()
        word = garbled(
            reply, [*names, *names.values(), self.channel, *self.own_names()]
        )
        if word:
            return "name", (
                f"\"{word}\" isn't anyone's name; write names exactly as they "
                "appear in chat"
            )
        if target is not None:
            problem = reply_problem(reply, target, recent, self.channel)
            if problem:
                return problem
        return None, None

    async def generate(
        self, messages, kind="reply", trigger="", test=False, target=None, recent=()
    ):
        """Ask the model, retrying twice if a filter rejects the reply.

        A blocked reply is logged, reported to the owner (except in tests), and
        the retry is told why it was blocked. Returns `(reply or None, reason
        it was dropped or None, metadata)`.
        """
        reason, data, drafts = None, {"drafts": []}, []
        messages = list(messages)
        for _ in range(ATTEMPTS):
            text, data = await self.client.chat(messages)
            data = {**(data or {}), "drafts": drafts}
            reply = clean_reply(text)
            if not reply:
                reason = "empty"
                drafts.append({"raw": text, "blocked": reason})
                continue
            reason, why = await self.check_reply(reply, target, recent)
            drafts.append({"raw": text, "blocked": reason})
            if reason is None:
                if not test:
                    self.said.append(reply)
                return reply, None, data
            await self.blocked(kind, reason, reply, trigger, notify=not test)
            messages += [
                {"role": "assistant", "content": reply},
                {
                    "role": "user",
                    "content": f"That message was blocked because {why}. Write a "
                    "different one that follows your rules.",
                },
            ]
        return None, reason, data

    async def blocked(self, kind, reason, text, trigger="", notify=True):
        """Log a blocked model output and tell the owner about it."""
        self.note(f"Blocked a {kind} ({reason}): {text[:80]}")
        entry_id = await asyncio.to_thread(
            self.bot.database.add_filtered, kind, reason, text, trigger
        )
        config = self.bot.config
        if reason in QUIET_REASONS:
            return
        if reason == "repetition" and not flag(config, "llm_notify_repetition", False):
            return
        if notify and flag(config, "llm_notify_filtered", True):
            await self.notify_blocked(entry_id, kind, reason, text, trigger)

    async def notify_blocked(self, entry_id, kind, reason, text, trigger):
        """DM the owner about a block, at most once per `llm_notify_seconds`."""
        gap = float(setting(self.bot.config, "llm_notify_seconds", 60))
        if time.monotonic() - self.last_notice < gap:
            self.unnoticed += 1
            return
        self.last_notice = time.monotonic()
        skipped, self.unnoticed = self.unnoticed, 0
        from cynthia.bot.applications.llm import FilteredView, filtered_embed

        entry = {
            "id": entry_id,
            "time": time.time(),
            "kind": kind,
            "reason": reason,
            "text": text,
            "trigger": trigger,
        }
        try:
            owner = await self.bot.fetch_user(int(self.bot.owner))
            await owner.send(
                embed=filtered_embed(entry, skipped),
                view=FilteredView(self.moderator, reason, text),
            )
        except Exception as e:
            logger.warning("Couldn't tell the owner about a blocked message: %s", e)

    def reload_moderator(self):
        """Rebuild the filter after the allowed or blocked words change."""
        config = self.bot.config
        self.moderator = Moderator(
            allow=names_list(config, "llm_allowed_words", []),
            block=names_list(config, "llm_blocked_words", []),
        )
        self.memory.moderator = self.moderator

    def fitted(self, build, parts):
        """Messages from `build(parts)`, trimmed to leave room for the reply."""
        config = self.bot.config
        budget = (
            int(setting(config, "llm_num_ctx", 4096))
            - int(setting(config, "llm_max_tokens", 80))
            - PROMPT_MARGIN
        )
        messages, used, trimmed = fit(build, parts, budget)
        if trimmed:
            dropped = ", ".join(f"{n} {key}" for key, n in trimmed.items())
            logger.info("Prompt trimmed to ~%d tokens (dropped %s).", used, dropped)
        return messages

    async def reply_to(self, message, prior, test=False):
        """Build context and generate an answer to `message`.

        Returns a dict with `reply`, `dropped`, `messages`, `context` and `data`.
        """
        parts = await self.context(message, prior)

        def build(p):
            return reply_messages(
                self.client.prompt,
                self.client.notes,
                p["lines"],
                p["memories"],
                p["recent"],
                message,
                p["history"],
                p["present"],
                p["lessons"],
                p["facts"],
                self.channel,
            )

        messages = self.fitted(build, parts)
        try:
            reply, dropped, data = await self.generate(
                messages,
                "reply",
                f"{message['user']}: {message['text']}",
                test,
                target=message,
                recent=parts["recent"],
            )
        except LLMError as e:
            self.note(f"Model error: {e}")
            reply, dropped, data = None, str(e), {}
        return {
            "reply": reply,
            "dropped": dropped,
            "messages": messages,
            "context": parts,
            "data": data,
        }

    async def event_prompt(self, kind="idle", detail="", recent=None):
        """Messages and context parts for a stream-event remark, fitted to the window.

        The system message is the same one replies get, minus per-chatter memories.
        """
        state = await self.state(0)
        recent = list(self.recent) if recent is None else recent
        recent = recent[-limit(self.bot.config, "llm_context_messages", 8) :]
        parts = {
            "lines": render(state),
            "recent": recent,
            "lessons": await self.guidance(),
            "facts": self.pokedex(state, [m["text"] for m in recent[-3:]]),
        }

        def build(p):
            return event_messages(
                self.client.prompt,
                self.client.notes,
                p["lines"],
                [],
                p["recent"],
                kind,
                detail,
                p["lessons"],
                p["facts"],
                self.channel,
            )

        return self.fitted(build, parts), parts

    async def remark(self, kind, detail="", recent=None, test=False):
        """Generate a remark about a stream event; same result shape as replies."""
        messages, _ = await self.event_prompt(kind, detail, recent)
        try:
            reply, dropped, data = await self.generate(
                messages, "event", f"{kind} event", test
            )
        except LLMError as e:
            reply, dropped, data = None, str(e), {}
        return {"reply": reply, "dropped": dropped, "messages": messages, "data": data}

    async def deliver(self, text, reply_to=None, login=None, event=False):
        """Send `text` to chat and/or speak it, as switched on.

        Returns whether it was posted to chat, or None when posting is off.
        """
        self.triggers.spoke(login, event=event)
        self.last_activity = time.monotonic()
        self.recent.append(chat_message("Cynthia", text, login="cynthia"))
        posted = None
        if self.enabled("speak"):
            posted = await self.post(text, reply_to)
        if self.enabled("voice"):
            self.speaking.add(asyncio.create_task(self.speak_in_background(text)))
        return posted

    async def post(self, text, reply_to=None):
        """Post `text` to Twitch chat; returns whether it went out."""
        api = self.chat_api
        if api is None:
            self.note("Can't post: Twitch isn't set up.")
            return False
        key = echo_key(text)
        self.sent.append(key)
        try:
            broadcaster = self.twitch_api
            if broadcaster is None or not broadcaster.tokens.get("user_id"):
                raise LLMError("Authorize the broadcaster with `/twitch auth`.")
            message_id = await api.send_chat_message(
                text,
                reply_to=reply_to,
                broadcaster_id=broadcaster.tokens["user_id"],
            )
        except Exception as e:
            if key in self.sent:
                self.sent.remove(key)
            self.note(f"Couldn't post to chat: {e}")
            return False
        if message_id:
            self.sent_ids.append(message_id)
        self.note(f"Said: {text}")
        return True

    async def announce(self, key):
        """Post the fixed config message `key` (not the model) while live.

        Used for `twitch_reboot_message` and `twitch_goodbye_message`; skipped
        when it's blank or OBS is known not to be streaming.
        """
        text = " ".join(str(self.bot.config.get(key, "")).split())
        if not text or not self.channel:
            return False
        obs = self.bot.get_cog("OBSCog")
        status = getattr(obs, "last_status", None)
        if obs is not None and not (status or {}).get("streaming"):
            return False
        return await self.post(text[:MAX_CHAT])

    async def speak_in_background(self, text):
        """Speak without raising; failures are already in `/llm log`."""
        try:
            await self.say_aloud(text)
        except Exception:
            pass
        finally:
            self.speaking.discard(asyncio.current_task())

    async def say_aloud(self, text):
        """Read `text` on stream; returns the speech length in seconds."""
        obs = getattr(self.bot, "obs", None)
        if obs is None:
            raise RuntimeError("OBS isn't set up, so there's nowhere to speak.")
        if self.speaker is None or self.speaker.obs is not obs:
            self.speaker = Speaker(self.voice, obs)
        try:
            return await self.speaker.say(text)
        except Exception as e:
            self.note(f"Couldn't speak: {e}")
            raise

    # -- owner conversation -------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message):
        """In talk mode, answer the owner's plain DMs and learn from them."""
        if (
            message.guild is not None
            or message.author.bot
            or str(message.author.id) != str(self.bot.owner)
            or not self.enabled("talk")
            or not message.content.strip()
            or message.content.startswith(("/", "!"))
        ):
            return
        async with message.channel.typing():
            text = await self.teach(message.author.display_name, message.content)
        await message.reply(text, mention_author=False)

    async def teach(self, owner, text):
        """One owner conversation turn, as Discord text with any lesson changes."""
        try:
            reply, changes = await self.teacher.talk(owner, text)
        except LLMError as e:
            return f"❌ {e}"
        lines = [reply or "…"]
        if changes:
            lines.append("-# " + "\n-# ".join(changes))
        out = "\n".join(lines)
        return out if len(out) <= DISCORD_LIMIT else out[: DISCORD_LIMIT - 1] + "…"

    # -- events and memory ---------------------------------------------------

    def read_counters(self):
        """Current event counters from the shared daemon namespace."""
        uns = self.bot.dman.uns
        counts = {kind: getattr(uns, name, 0) or 0 for kind, name in COUNTERS.items()}
        counts["shiny"] = bool(getattr(uns, "nxbt_daemon_stop", False))
        return counts

    @tasks.loop(seconds=EVENT_SECONDS)
    async def watch_events(self):
        """Notice hunt events and long silences, and maybe remark on them."""
        try:
            counts = await asyncio.to_thread(self.read_counters)
        except (AttributeError, EOFError, OSError):
            return
        previous, self.counters = self.counters, counts
        if previous is None:
            return
        happened = [
            kind
            for kind in EVENT_ORDER
            if (
                counts[kind] and not previous[kind]
                if kind == "shiny"
                else counts[kind] > previous[kind]
            )
        ]
        idle = time.monotonic() - self.last_activity > self.triggers.idle_seconds()
        if idle:
            happened.append("idle")
        if not self.enabled("events") or not happened or not await self.may_talk():
            return
        for kind in happened:
            if not self.triggers.event(kind):
                continue
            self.note(f"Remarking on {kind}.")
            result = await self.remark(kind)
            entry = {
                "type": "event",
                "event": kind,
                "prompt": result.get("messages"),
                "drafts": (result.get("data") or {}).get("drafts", []),
                "reply": result["reply"],
                "dropped": result.get("dropped"),
            }
            if result["reply"] and self.enabled("events"):
                entry["posted"] = await self.deliver(result["reply"], event=True)
            else:
                self.last_activity = time.monotonic()
            await asyncio.to_thread(self.journal.write, entry)
            return
        if idle:
            self.last_activity = time.monotonic()

    @watch_events.before_loop
    async def before_events(self):
        """Wait for Discord so the daemons are up."""
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=MEMORY_SECONDS)
    async def learn_memories(self):
        """Update notes for chatters with enough new messages."""
        if not self.enabled("learn") or not self.bot.database.database_connected:
            return
        learned = await self.memory.learn_pending()
        if learned:
            self.note("Updated notes for " + ", ".join(learned) + ".")

    @learn_memories.before_loop
    async def before_memories(self):
        """Wait for Discord before using the model."""
        await self.bot.wait_until_ready()


async def setup(bot):
    """Register the chat model cog."""
    await bot.add_cog(LLMChatCog(bot))
