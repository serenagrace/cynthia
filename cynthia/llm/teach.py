"""Let the owner talk with the chat model and teach it lasting lessons.

Each owner message gets one model call that returns JSON: a conversational
reply plus edits to the numbered lessons (or a note on a Twitch chatter).
The edits are checked here before they're stored, and the lessons are added
to every chat prompt.
"""

import asyncio
import json
import logging
import re

from .client import clean_reply, setting

logger = logging.getLogger(__name__)

SECTIONS = {
    "behavior": "How to act and when",
    "style": "How to talk",
    "facts": "Facts about the stream, channel and streamer",
    "people": "About regular viewers",
}
MAX_LESSON_CHARS = 300

CURATOR = """You are talking privately with {owner}, the streamer who runs you. \
Here they can chat with you, give feedback on how you act in Twitch chat, and \
teach you things. You keep what they teach as numbered lessons in sections: \
behavior (how to act and when), style (how to talk), facts (about the stream, \
channel, games and streamer) and people (about regular viewers).

Each time, decide whether your lessons should change:
- add: something new they want you to remember or do from now on
- update: they refine, correct or reverse an existing lesson (use its id)
- remove: they ask you to stop doing or forget a lesson (use its id)
- chatter: a fact about one Twitch viewer, by their login name
Write lessons as one short sentence, as an instruction to yourself or a fact. \
Don't save small talk, questions, one-off requests, or anything that breaks your \
safety rules; those rules always win. Change nothing if nothing should change. \
In your reply, talk back naturally in your own personality and briefly say what \
you'll remember or forget.

Answer with JSON only, like:
{{"reply": "got it!", "actions": [{{"op": "add", "section": "style", "text": "..."}}, \
{{"op": "update", "id": 3, "text": "..."}}, {{"op": "remove", "id": 5}}, \
{{"op": "chatter", "login": "name", "text": "..."}}]}}"""


def lesson_lines(lessons):
    """Lessons grouped by section, for the chat prompt."""
    lines = []
    for section, title in SECTIONS.items():
        texts = [lesson["text"] for lesson in lessons if lesson["section"] == section]
        if texts:
            lines.append(f"{title}:")
            lines += [f"- {text}" for text in texts]
    return lines


def numbered(lessons):
    """Lessons with their ids, for the teaching prompt."""
    if not lessons:
        return "(none yet)"
    return "\n".join(f"[{l['id']}] ({l['section']}) {l['text']}" for l in lessons)


def teach_messages(persona, owner, lessons, history, text):
    """Messages for one turn of the owner conversation."""
    messages = [
        {"role": "system", "content": persona + "\n\n" + CURATOR.format(owner=owner)}
    ]
    for turn in history:
        role = "user" if turn["role"] == "owner" else "assistant"
        messages.append({"role": role, "content": turn["text"]})
    messages.append(
        {
            "role": "user",
            "content": f"Your lessons now:\n{numbered(lessons)}\n\n{owner}: {text}",
        }
    )
    return messages


def parse(text):
    """The model's JSON answer as `(reply, actions)`; tolerates stray text."""
    match = re.search(r"\{.*\}", text, re.S)
    try:
        data = json.loads(match.group(0) if match else text)
    except (json.JSONDecodeError, AttributeError):
        return clean_reply(text), []
    if not isinstance(data, dict):
        return "", []
    actions = data.get("actions") or []
    return clean_reply(str(data.get("reply") or "")), (
        [a for a in actions if isinstance(a, dict)] if isinstance(actions, list) else []
    )


def lesson_text(action):
    """An action's text, tidied, or None when it's unusable."""
    text = " ".join(str(action.get("text") or "").split())
    return text[:MAX_LESSON_CHARS] if text else None


class Teacher:
    """Hold the owner conversation and apply the lessons it produces."""

    def __init__(self, config, database, client):
        """Use the bot `database` for lessons and the LLM `client`."""
        self.config = config
        self.database = database
        self.client = client

    @property
    def max_lessons(self):
        """Most lessons kept at once."""
        return int(setting(self.config, "llm_lessons_max", 40))

    async def lessons(self):
        """All stored lessons."""
        return await asyncio.to_thread(self.database.lessons)

    async def talk(self, owner, text):
        """One turn: returns `(reply, changes)` where changes describe edits."""
        lessons = await self.lessons()
        history = await asyncio.to_thread(
            self.database.owner_chat, int(setting(self.config, "llm_owner_history", 12))
        )
        messages = teach_messages(self.client.prompt, owner, lessons, history, text)
        raw, _ = await self.client.chat(
            messages, max_tokens=400, temperature=0.4, json_format=True
        )
        reply, actions = parse(raw)
        changes = await self.apply(actions, lessons)
        await asyncio.to_thread(self.database.add_owner_chat, "owner", text)
        if reply:
            await asyncio.to_thread(self.database.add_owner_chat, "cynthia", reply)
        return reply, changes

    async def apply(self, actions, lessons):
        """Store valid lesson edits; returns a line describing each change."""
        known = {lesson["id"]: lesson for lesson in lessons}
        count = len(lessons)
        changes = []
        for action in actions:
            op = str(action.get("op", "")).lower()
            text = lesson_text(action)
            try:
                lesson_id = int(action.get("id"))
            except (TypeError, ValueError):
                lesson_id = None
            if op == "add" and text:
                section = str(action.get("section", "")).lower()
                section = section if section in SECTIONS else "behavior"
                if count >= self.max_lessons:
                    changes.append(f"⚠️ Lesson limit reached; didn't add: {text}")
                    continue
                new_id = await asyncio.to_thread(
                    self.database.add_lesson, section, text
                )
                count += 1
                changes.append(f"➕ [{new_id}] ({section}) {text}")
            elif op == "update" and text and lesson_id in known:
                await asyncio.to_thread(self.database.update_lesson, lesson_id, text)
                changes.append(f"✏️ [{lesson_id}] {text}")
            elif op == "remove" and lesson_id in known:
                await asyncio.to_thread(self.database.remove_lesson, lesson_id)
                count -= 1
                changes.append(f"➖ [{lesson_id}] {known[lesson_id]['text']}")
            elif op == "chatter" and text and action.get("login"):
                login = str(action["login"]).strip().lstrip("@").lower()
                await self.note_chatter(login, text)
                changes.append(f"👤 {login}: {text}")
            elif op:
                logger.debug("Ignored lesson action %s.", action)
        return changes

    async def note_chatter(self, login, text):
        """Add an owner-given fact to a chatter's notes."""
        row = await asyncio.to_thread(self.database.chatter, login)
        notes = ((row or {}).get("notes") or "").strip()
        limit = int(setting(self.config, "llm_memory_max_chars", 500))
        notes = f"{notes} {text}".strip()[-limit:]
        await asyncio.to_thread(self.database.set_chatter_notes, login, notes)
