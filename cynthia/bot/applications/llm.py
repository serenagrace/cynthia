"""Owner-only DM commands to control and test the local chat model."""

import asyncio
import io
import json
import time

import discord
from discord import app_commands

from cynthia.bot.cogs.llmchat import chat_message
from cynthia.llm.client import LLMError
from cynthia.llm.memory import beliefs
from cynthia.llm.moderation import LESSONS, culprits, explain
from cynthia.llm.prompt import estimate_tokens, limit
from cynthia.llm.pronouns import describe
from cynthia.llm.state import render
from cynthia.llm.teach import SECTIONS
from cynthia.llm.triggers import (
    EVENT_CHANCES,
    REPLY_CHANCES,
    chance,
    classify,
    names_list,
)
from cynthia.llm.voice import VoiceError
from cynthia.utils.auth import OwnerGroup
from cynthia.utils.embeds import BRAND, make_embed
from cynthia.utils.twitchapi import CHAT_SCOPE

# Discord's limit for a modal text field
FIELD_LIMIT = 4000
NONE = discord.AllowedMentions.none()
EVENT_KINDS = [app_commands.Choice(name=kind, value=kind) for kind in EVENT_CHANCES]

llm = OwnerGroup(name="llm", description="Control and test the local chat model.")


class NotReady(app_commands.CheckFailure):
    """The chat model cog isn't loaded."""


def get_cog(interaction):
    """The running chat model cog."""
    cog = interaction.client.get_cog("LLMChatCog")
    if cog is None:
        raise NotReady("The chat model cog isn't loaded.")
    return cog


def shorten(text, size):
    """Trim `text` to `size` characters for an embed."""
    return text if len(text) <= size else text[: size - 1] + "…"


def prompt_file(messages, name="prompt.txt"):
    """The full prompt as a text attachment."""
    text = "\n\n".join(f"### {m['role']}\n{m['content']}" for m in messages)
    return discord.File(io.BytesIO(text.encode()), filename=name)


def timing(data):
    """How long the model took, from Ollama's response metadata."""
    seconds = data.get("total_duration", 0) / 1e9
    return f"{seconds:.1f}s" if seconds else "?"


def login_of(name):
    """A Twitch login from a typed name."""
    return name.strip().lstrip("@").lower()


class TextModal(discord.ui.Modal):
    """Edit one long config value, such as the persona or notes."""

    def __init__(self, title, key, label, value, placeholder):
        """Prefill the field with the current value of config `key`."""
        super().__init__(title=title)
        self.key = key
        self.field = discord.ui.TextInput(
            label=label,
            style=discord.TextStyle.paragraph,
            default=value[:FIELD_LIMIT],
            placeholder=placeholder,
            max_length=FIELD_LIMIT,
            required=False,
        )
        self.add_item(self.field)

    async def on_submit(self, interaction: discord.Interaction):
        """Save the new value; it's written to the config file at shutdown."""
        interaction.client.config.set(self.key, self.field.value.strip())
        await interaction.response.send_message(
            f"✅ Saved `{self.key}` ({len(self.field.value.strip())} characters)."
        )


class NotesModal(discord.ui.Modal):
    """Edit the remembered notes about one chatter."""

    def __init__(self, login, notes, max_chars):
        """Prefill the chatter's current notes."""
        super().__init__(title=f"Notes on {login}"[:45])
        self.login = login
        self.field = discord.ui.TextInput(
            label="Notes",
            style=discord.TextStyle.paragraph,
            default=notes[:max_chars],
            max_length=max_chars,
            required=False,
        )
        self.add_item(self.field)

    async def on_submit(self, interaction: discord.Interaction):
        """Store the edited notes in the database."""
        await asyncio.to_thread(
            interaction.client.database.set_chatter_notes,
            self.login,
            self.field.value.strip(),
        )
        await interaction.response.send_message(f"✅ Saved notes on `{self.login}`.")


# -- trying it out -------------------------------------------------------------


@llm.command(name="say", description="Send a test chat message through the pipeline.")
@app_commands.describe(
    message="What the chatter says",
    user="Chatter the model sees; a real login uses their memory and history",
    show_prompt="Attach the full prompt the model got",
    real_chat="Use the real recent chat instead of the test conversation",
    send="Also send the reply to Twitch chat / voice if they're switched on",
)
async def say(
    interaction: discord.Interaction,
    message: str,
    user: str = None,
    show_prompt: bool = False,
    real_chat: bool = False,
    send: bool = False,
):
    """Answer `message` as if `user` typed it, without storing anything."""
    cog = get_cog(interaction)
    name = (user or interaction.user.display_name).strip().lstrip("@")[:25]
    await interaction.response.defer(thinking=True)
    test = chat_message(name, message)
    reason = await asyncio.to_thread(cog.moderator.check, message)
    if reason:
        await interaction.followup.send(
            f"🚫 Incoming moderation would flag this ({reason}); it wouldn't be "
            "answered or learned from."
        )
        return
    prior = list(cog.recent if real_chat else cog.sandbox)
    result = await cog.reply_to(test, prior, test=True)
    if not real_chat:
        cog.sandbox.append(test)
    lines = [f"**{discord.utils.escape_markdown(name)}:** {message}"]
    if result["reply"]:
        lines.append(f"**Cynthia:** {result['reply']}")
        if not real_chat:
            cog.sandbox.append(chat_message("Cynthia", result["reply"], "cynthia"))
    else:
        lines.append(f"🚫 No reply ({result['dropped']}).")
    parts = result["context"]
    used = [
        f"{len(parts['recent'])} recent",
        f"{len(parts['history'])} earlier from them",
        f"{len(parts['memories'])} memories",
    ]
    if parts["mentioned"]:
        used.append("mentioned " + ", ".join(parts["mentioned"]))
    lines.append(f"-# {timing(result['data'])} · " + " · ".join(used))
    files = [prompt_file(result["messages"])] if show_prompt else []
    await interaction.followup.send(
        "\n".join(lines), files=files, allowed_mentions=NONE
    )
    if send and result["reply"]:
        await cog.deliver(result["reply"], login=test["login"])


@llm.command(name="event", description="Have the model remark on a stream event.")
@app_commands.describe(
    kind="Which event to pretend happened",
    show_prompt="Attach the full prompt the model got",
    send="Also send it to Twitch chat / voice if they're switched on",
)
@app_commands.choices(kind=EVENT_KINDS)
async def event(
    interaction: discord.Interaction,
    kind: app_commands.Choice[str],
    show_prompt: bool = False,
    send: bool = False,
):
    """Generate the remark the bot would make for an event."""
    cog = get_cog(interaction)
    await interaction.response.defer(thinking=True)
    result = await cog.remark(kind.value, test=True)
    odds = chance(
        interaction.client.config,
        f"llm_event_{kind.value}_chance",
        EVENT_CHANCES[kind.value],
    )
    text = (
        f"**Cynthia:** {result['reply']}"
        if result["reply"]
        else f"🚫 No remark ({result['dropped']})."
    )
    files = [prompt_file(result["messages"])] if show_prompt else []
    await interaction.followup.send(
        f"{text}\n-# {timing(result['data'])} · live chance {odds:.0%}",
        files=files,
        allowed_mentions=NONE,
    )
    if send and result["reply"]:
        await cog.deliver(result["reply"], event=True)


@llm.command(name="state", description="Show the live state the model is told about.")
async def state(interaction: discord.Interaction):
    """Show the rendered state and the raw snapshot."""
    cog = get_cog(interaction)
    await interaction.response.defer(thinking=True)
    snapshot = await cog.state(0)
    raw = json.dumps(snapshot, indent=2, default=str)
    await interaction.followup.send(
        embed=make_embed(
            "Right now", shorten("\n".join(render(snapshot)), 4000), color=BRAND
        ),
        file=discord.File(io.BytesIO(raw.encode()), filename="state.json"),
    )


@llm.command(name="moderate", description="Check text against the chat filter.")
@app_commands.describe(text="Text to check")
async def moderate(interaction: discord.Interaction, text: str):
    """Show how the filter treats `text` as incoming chat and as a reply."""
    cog = get_cog(interaction)
    incoming = await asyncio.to_thread(cog.moderator.check, text)
    outgoing = await asyncio.to_thread(cog.moderator.check, text, True)
    await interaction.response.send_message(
        f"Incoming chat: {'🚫 ' + incoming if incoming else '✅ clean'}\n"
        f"Model reply: {'🚫 ' + outgoing if outgoing else '✅ clean'}"
    )


@llm.command(name="trigger", description="Check whether a message would get a reply.")
@app_commands.describe(text="Chat message", user="Who sends it")
async def trigger(interaction: discord.Interaction, text: str, user: str = "viewer"):
    """Explain the trigger decision for `text` without rolling or replying."""
    cog = get_cog(interaction)
    config = interaction.client.config
    triggers = cog.triggers
    kind = classify(config, text, cog.own_names())
    login = login_of(user)
    lines = [f"Kind: **{kind or 'never answered'}**"]
    if kind:
        odds = chance(config, f"llm_reply_{kind}_chance", REPLY_CHANCES[kind])
        lines.append(f"Chance: {odds:.0%} (`llm_reply_{kind}_chance`)")
    if triggers.cooling(triggers.last_reply, "llm_reply_cooldown_seconds", 30):
        lines.append("⏳ The global cooldown is running (mentions skip it).")
    if triggers.cooling(triggers.last_user.get(login), "llm_user_cooldown_seconds", 20):
        lines.append(f"⏳ `{login}`'s cooldown is running.")
    if not await cog.may_talk():
        lines.append("🔇 Nothing would be sent: speak/voice are off or not live.")
    await interaction.response.send_message("\n".join(lines))


# -- chatter memory ------------------------------------------------------------


async def chatter_names(interaction: discord.Interaction, current: str):
    """Autocomplete known Twitch chatters."""
    rows, _ = await asyncio.to_thread(
        interaction.client.database.list_chatters, current.strip().lstrip("@"), 25
    )
    return [
        app_commands.Choice(name=row["display"] or row["login"], value=row["login"])
        for row in rows
    ]


async def resolve(interaction, user):
    """The login for a login, display name or common nickname."""
    login = login_of(user)
    found = await asyncio.to_thread(interaction.client.database.resolve_chatter, login)
    return found or login


def memory_embed(row, recent):
    """A chatter's notes, stats and latest messages."""
    said = "\n".join(f"> {m['text']}" for m in recent) or "—"
    learned = row["learned_until"] or 0
    return make_embed(
        row["display"] or row["login"],
        shorten(row["notes"] or "No notes yet.", 4000),
        color=BRAND,
        fields=[
            ("Login", f"`{row['login']}`"),
            ("Messages", row["message_count"] or 0),
            ("Streams", row["streams"] or 0),
            (
                "Pronouns",
                f"{describe(row.get('pronoun_evidence') or []) or 'unknown (they/them)'}"
                f" · {len(row.get('pronoun_evidence') or [])} clues",
            ),
            ("Nicknames", nickname_text(row) or "none"),
            (
                "Others say (unconfirmed)",
                shorten(
                    "\n".join(
                        f"~{round(sure * 100)}% {fact} (by {', '.join(by)})"
                        for fact, sure, by in beliefs(row.get("hearsay") or [])[:5]
                    )
                    or "nothing",
                    1000,
                ),
                False,
            ),
            (
                "Tone to Cynthia",
                f"{row.get('kind_count') or 0} kind · {row.get('rude_count') or 0} rude",
            ),
            ("First seen", f"<t:{int(row['first_seen'] or 0)}:R>"),
            ("Last seen", f"<t:{int(row['last_seen'] or 0)}:R>"),
            ("Learned up to", f"<t:{int(learned)}:R>" if learned else "never"),
            ("Recent messages", shorten(said, 1000), False),
        ],
    )


def nickname_text(row):
    """A chatter's nicknames with use counts; established ones first."""
    nicks = sorted(row.get("nicknames") or [], key=lambda n: -n["uses"])
    return ", ".join(f"{n['nickname']} ×{n['uses']}" for n in nicks[:10])


def memory_file(row, messages):
    """A chatter's notes and stored messages as a text attachment."""
    lines = [
        f"# {row['display'] or row['login']} ({row['login']})",
        "",
        "## Notes",
        row["notes"] or "(none)",
        "",
        f"## Pronoun clues ({len(row.get('pronoun_evidence') or [])})",
        *(
            f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(e['time']))} "
            f"{e['pronouns']} ({e['kind']}, by {e['by_login']}): {e['text']}"
            for e in row.get("pronoun_evidence") or []
        ),
        "",
        f"## Nicknames: {nickname_text(row) or 'none'}",
        "",
        f"## What others said, unconfirmed ({len(row.get('hearsay') or [])})",
        *(
            f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(h['time']))} "
            f"{h['fact']} (by {h['by_login']}: \"{h['quote']}\")"
            for h in row.get("hearsay") or []
        ),
        "",
        f"## Messages ({len(messages)})",
    ]
    lines += [
        f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(m['time']))} {m['text']}"
        for m in messages
    ]
    return discord.File(
        io.BytesIO("\n".join(lines).encode()), filename=f"{row['login']}.txt"
    )


class MemoryView(discord.ui.View):
    """Buttons to edit, refresh, download or forget one chatter's memory."""

    def __init__(self, login, max_chars):
        """Act on `login`; notes are capped at `max_chars`."""
        super().__init__(timeout=900)
        self.login = login
        self.max_chars = max_chars
        self.confirming = False

    async def row(self, interaction):
        """The chatter's current memory row."""
        return await asyncio.to_thread(interaction.client.database.chatter, self.login)

    @discord.ui.button(
        label="Edit notes", emoji="✏️", style=discord.ButtonStyle.primary
    )
    async def edit(self, interaction: discord.Interaction, _button):
        """Open the notes editor."""
        row = await self.row(interaction) or {}
        await interaction.response.send_modal(
            NotesModal(self.login, row.get("notes") or "", self.max_chars)
        )

    @discord.ui.button(label="Refresh", emoji="🔄")
    async def refresh(self, interaction: discord.Interaction, _button):
        """Show the latest notes and messages."""
        row = await self.row(interaction)
        if row is None:
            await interaction.response.edit_message(
                content=f"`{self.login}` is forgotten.", embed=None, view=None
            )
            return
        recent = await asyncio.to_thread(
            interaction.client.database.chat_messages, self.login, 0, 5
        )
        await interaction.response.edit_message(embed=memory_embed(row, recent))

    @discord.ui.button(label="Download", emoji="📄")
    async def download(self, interaction: discord.Interaction, _button):
        """Attach the notes and every stored message as a text file."""
        row = await self.row(interaction)
        if row is None:
            await interaction.response.send_message(f"I don't know `{self.login}`.")
            return
        messages = await asyncio.to_thread(
            interaction.client.database.chat_messages, self.login, 0, 10000
        )
        await interaction.response.send_message(file=memory_file(row, messages))

    @discord.ui.button(label="Forget", emoji="🧹", style=discord.ButtonStyle.danger)
    async def forget(self, interaction: discord.Interaction, button):
        """Delete the chatter's memory after a second click."""
        if not self.confirming:
            self.confirming = True
            button.label = "Click again to forget"
            await interaction.response.edit_message(view=self)
            return
        await asyncio.to_thread(interaction.client.database.forget_chatter, self.login)
        await interaction.response.edit_message(
            content=f"🧹 Forgot `{self.login}`.", embed=None, view=None
        )


@llm.command(
    name="memory", description="View and edit what's remembered about a chatter."
)
@app_commands.describe(user="Twitch login")
@app_commands.autocomplete(user=chatter_names)
async def memory(interaction: discord.Interaction, user: str):
    """Show a chatter's notes with buttons to edit, download or forget them."""
    cog = get_cog(interaction)
    login = await resolve(interaction, user)
    database = interaction.client.database
    row = await asyncio.to_thread(database.chatter, login)
    view = MemoryView(login, cog.memory.max_chars)
    if row is None:
        await interaction.response.send_message(
            f"I don't know `{login}` yet; add notes to start their memory.",
            view=view,
        )
        return
    recent = await asyncio.to_thread(database.chat_messages, login, 0, 5)
    await interaction.response.send_message(
        embed=memory_embed(row, recent), view=view, allowed_mentions=NONE
    )


@llm.command(name="memories", description="List the chatters the model remembers.")
@app_commands.describe(search="Filter by name or notes", page="Page number")
async def memories(
    interaction: discord.Interaction,
    search: str = "",
    page: app_commands.Range[int, 1, 1000] = 1,
):
    """List chatters, most recently seen first."""
    per_page = 15
    rows, total = await asyncio.to_thread(
        interaction.client.database.list_chatters,
        search.strip(),
        per_page,
        (page - 1) * per_page,
    )
    lines = [
        f"**{discord.utils.escape_markdown(r['display'] or r['login'])}** · "
        f"{r['message_count'] or 0} msgs · <t:{int(r['last_seen'] or 0)}:R>\n"
        f"-# {shorten(r['notes'] or 'no notes yet', 150)}"
        for r in rows
    ]
    pages = max((total + per_page - 1) // per_page, 1)
    embed = make_embed(
        f"Chatters ({total})",
        shorten("\n".join(lines) or "Nobody yet.", 4000),
        color=BRAND,
    )
    embed.set_footer(text=f"Page {page}/{pages} · /llm memory <login> to edit")
    await interaction.response.send_message(embed=embed, allowed_mentions=NONE)


@llm.command(
    name="learn", description="Update a chatter's notes from their new messages now."
)
@app_commands.describe(user="Twitch login")
@app_commands.autocomplete(user=chatter_names)
async def learn(interaction: discord.Interaction, user: str):
    """Run the memory update for one chatter immediately."""
    cog = get_cog(interaction)
    login = await resolve(interaction, user)
    await interaction.response.defer(thinking=True)
    try:
        notes = await cog.memory.learn(login)
    except LLMError as e:
        await interaction.followup.send(f"❌ {e}")
        return
    if notes is None:
        await interaction.followup.send(f"Nothing new to learn about `{login}`.")
        return
    await interaction.followup.send(
        f"📝 Notes on `{login}`:\n{notes or '(none)'}", allowed_mentions=NONE
    )


# -- teaching ------------------------------------------------------------------


@llm.command(
    name="teach", description="Talk with Cynthia; she remembers what you teach her."
)
@app_commands.describe(message="What you want to tell her")
async def teach(interaction: discord.Interaction, message: str):
    """One owner conversation turn; lesson changes are listed under the reply."""
    cog = get_cog(interaction)
    await interaction.response.defer(thinking=True)
    text = await cog.teach(interaction.user.display_name, message)
    await interaction.followup.send(
        f"> {shorten(message, 300)}\n{text}"[:2000], allowed_mentions=NONE
    )


@llm.command(name="lessons", description="List what you've taught Cynthia.")
async def lessons(interaction: discord.Interaction):
    """List lessons with their ids, grouped by section."""
    rows = await get_cog(interaction).teacher.lessons()
    lines = []
    for section, title in SECTIONS.items():
        texts = [f"`{r['id']}` {r['text']}" for r in rows if r["section"] == section]
        if texts:
            lines += [f"**{title}**", *texts, ""]
    embed = make_embed(
        f"Lessons ({len(rows)})",
        shorten("\n".join(lines) or "Nothing yet; try `/llm teach`.", 4000),
        color=BRAND,
    )
    embed.set_footer(text="/llm unlearn <id> removes one · /llm teach changes them")
    await interaction.response.send_message(embed=embed, allowed_mentions=NONE)


@llm.command(name="unlearn", description="Remove one lesson by its id.")
@app_commands.describe(lesson="Lesson id from /llm lessons")
async def unlearn(interaction: discord.Interaction, lesson: int):
    """Delete a lesson."""
    gone = await asyncio.to_thread(interaction.client.database.remove_lesson, lesson)
    await interaction.response.send_message(
        f"➖ Removed lesson `{lesson}`." if gone else f"No lesson `{lesson}`."
    )


# -- filtered replies ----------------------------------------------------------


def filtered_embed(entry, skipped=0):
    """Describe a blocked model output for the owner."""
    embed = make_embed(
        f"🚫 Blocked a {entry['kind']} ({entry['reason']})",
        shorten(entry["text"], 1500),
        color=discord.Color.orange(),
        fields=[
            ("Why", f"Because {explain(entry['reason'])}.", False),
            ("Answering", shorten(entry.get("trigger") or "—", 1000), False),
        ],
    )
    footer = f"#{entry.get('id') or '?'} · it was told why and tried again"
    if skipped:
        footer += f" · {skipped} more since the last notice (/llm filtered)"
    embed.set_footer(text=footer)
    embed.timestamp = discord.utils.utcnow()
    return embed


class FilteredView(discord.ui.View):
    """Turn a blocked reply into a lesson, or allow words the filter caught."""

    def __init__(self, moderator, reason, text):
        """Offer actions for one blocked `text`."""
        super().__init__(timeout=24 * 3600)
        self.lesson = LESSONS.get(reason)
        self.words = culprits(moderator, text) if reason == "profanity" else []
        if not self.lesson:
            self.remove_item(self.teach)
        if not self.words:
            self.remove_item(self.allow)
        else:
            self.allow.label = shorten("Allow " + ", ".join(self.words), 80)

    @discord.ui.button(label="Make it a lesson", emoji="📚")
    async def teach(self, interaction: discord.Interaction, button):
        """Store the rule this reply broke as a behavior lesson."""
        database = interaction.client.database
        existing = await asyncio.to_thread(database.lessons)
        if any(row["text"] == self.lesson for row in existing):
            text = "Cynthia already has that lesson."
        else:
            lesson_id = await asyncio.to_thread(
                database.add_lesson, "behavior", self.lesson
            )
            text = f"📚 Added lesson `{lesson_id}`: {self.lesson}"
        button.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(text)

    @discord.ui.button(label="Allow", emoji="✅", style=discord.ButtonStyle.secondary)
    async def allow(self, interaction: discord.Interaction, button):
        """Let these words through the filter from now on (a false positive)."""
        config = interaction.client.config
        allowed = names_list(config, "llm_allowed_words", [])
        allowed += [word for word in self.words if word not in allowed]
        config.set("llm_allowed_words", allowed)
        cog = interaction.client.get_cog("LLMChatCog")
        if cog is not None:
            await asyncio.to_thread(cog.reload_moderator)
        button.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            "✅ Allowed " + ", ".join(f"`{w}`" for w in self.words) + "."
        )


@llm.command(name="filtered", description="Show replies the filters blocked lately.")
@app_commands.describe(hours="How far back to look")
async def filtered(
    interaction: discord.Interaction, hours: app_commands.Range[int, 1, 720] = 24
):
    """List recent blocked outputs with their reasons."""
    rows = await asyncio.to_thread(
        interaction.client.database.filtered, time.time() - hours * 3600, 20
    )
    lines = [
        f"<t:{int(r['time'])}:R> **{r['reason']}** ({r['kind']}) "
        f"{shorten(r['text'], 150)}"
        for r in rows
    ]
    embed = make_embed(
        f"Blocked in the last {hours}h ({len(rows)})",
        shorten("\n".join(lines) or "Nothing was blocked.", 4000),
        color=BRAND,
    )
    await interaction.response.send_message(embed=embed, allowed_mentions=NONE)


# -- switches ------------------------------------------------------------------

SWITCHES = {
    "all": "Everything at once (reading, learning, posting, voice, DMs)",
    "listen": "Reading Twitch chat",
    "learn": "Learning chatter memories",
    "speak": "Posting replies in Twitch chat",
    "voice": "Speaking replies on stream",
    "talk": "Talking with you in plain DMs",
}


@llm.command(
    name="switch",
    description="Turn the chat model on/off, or just its listening, learning, speaking, voice or DMs.",
)
@app_commands.describe(name="What to switch", enabled="On or off; leave empty to check")
@app_commands.choices(
    name=[app_commands.Choice(name=v, value=k) for k, v in SWITCHES.items()]
)
async def switch(
    interaction: discord.Interaction,
    name: app_commands.Choice[str] = None,
    enabled: bool = None,
):
    """Show every switch, or show/set one."""
    cog = get_cog(interaction)
    if name is None:
        await interaction.response.send_message(
            "\n".join(
                f"{'✅' if cog.enabled(key) else '❌'} {label} (`{key}`)"
                for key, label in SWITCHES.items()
            )
        )
        return
    key = name.value
    if enabled is not None:
        cog.set_enabled(key, enabled)
    on = cog.enabled(key)
    text = f"{SWITCHES[key]} is **{'on' if on else 'off'}**."
    if key != "all" and not cog.enabled("all"):
        text += (
            "\n-# Everything is off with the `all` switch; this applies once it's on."
        )
    if key == "all" and on:
        text += "\n" + ", ".join(
            f"{k} {'✅' if cog.enabled(k) else '❌'}" for k in SWITCHES if k != "all"
        )
    api = cog.chat_api
    if key == "speak" and on and (api is None or not api.has_scope(CHAT_SCOPE)):
        text += (
            f"\n⚠️ Twitch hasn't granted chat posting yet; run `{api.auth_command}` again."
            if api is not None
            else "\n⚠️ Twitch isn't set up; run `/twitch auth` after configuring it."
        )
    if key == "listen" and on and not cog.channel:
        text += "\n⚠️ `TWITCH_CHANNEL` isn't set in `.env`."
    if key == "voice" and on and getattr(interaction.client, "obs", None) is None:
        text += "\n⚠️ OBS isn't set up, so there's nowhere to speak."
    if key in ("speak", "voice") and on and not await cog.may_talk():
        text += "\n-# Only while live (set `llm_speak_offline` to talk offline)."
    if key == "talk" and on:
        text += "\n-# Message me here without a `/` and I'll answer and learn."
    await interaction.response.send_message(text)


# -- text to speech ------------------------------------------------------------


@llm.command(name="tts", description="Hear text in Cynthia's voice.")
@app_commands.describe(
    text="What to say",
    on_stream="Also play it on stream through OBS",
)
async def tts(interaction: discord.Interaction, text: str, on_stream: bool = False):
    """Synthesize `text` and attach it; optionally play it on stream."""
    cog = get_cog(interaction)
    await interaction.response.defer(thinking=True)
    try:
        started = time.monotonic()
        path, seconds = await cog.voice.speak_to_file(text, "preview.wav")
        took = time.monotonic() - started
    except (VoiceError, ValueError) as e:
        await interaction.followup.send(f"❌ {e}")
        return
    note = f"-# `{cog.voice.name}` · {seconds:.1f}s of speech in {took:.1f}s"
    if on_stream:
        try:
            await cog.say_aloud(text)
            note += " · played on stream"
        except Exception as e:
            note += f" · ❌ couldn't play on stream: {e}"
    await interaction.followup.send(note, file=discord.File(path))


@llm.command(name="voices", description="List Piper voices you can pick.")
@app_commands.describe(language="Language code prefix, like en_US, en_GB or en")
async def voices(interaction: discord.Interaction, language: str = "en"):
    """List downloadable voices for a language."""
    cog = get_cog(interaction)
    await interaction.response.defer(thinking=True)
    try:
        catalog = await asyncio.to_thread(cog.voice.catalog)
    except Exception as e:
        await interaction.followup.send(f"❌ Couldn't load the voice list: {e}")
        return
    installed = set(cog.voice.installed())
    names = sorted(n for n in catalog if n.lower().startswith(language.lower()))
    lines = []
    for name in names:
        speakers = catalog[name].get("num_speakers", 1)
        extra = f" ({speakers} speakers)" if speakers > 1 else ""
        mark = "✅ " if name in installed else ""
        current = " ← current" if name == cog.voice.name else ""
        lines.append(f"{mark}`{name}`{extra}{current}")
    text = "\n".join(lines) or "No voices match."
    embed = make_embed(f"Voices ({len(names)})", shorten(text, 4000), color=BRAND)
    embed.set_footer(text="Previews: rhasspy.github.io/piper-samples · /llm setvoice")
    await interaction.followup.send(embed=embed)


async def voice_names(interaction: discord.Interaction, current: str):
    """Autocomplete Piper voice names."""
    cog = interaction.client.get_cog("LLMChatCog")
    if cog is None:
        return []
    try:
        catalog = await asyncio.to_thread(cog.voice.catalog)
    except Exception:
        catalog = {name: {} for name in cog.voice.installed()}
    current = current.lower()
    names = [n for n in sorted(catalog) if current in n.lower()]
    return [app_commands.Choice(name=n, value=n) for n in names[:25]]


@llm.command(
    name="setvoice", description="Pick Cynthia's voice (downloads it if needed)."
)
@app_commands.describe(
    name="Piper voice, like en_US-amy-medium",
    speaker="Speaker number for multi-speaker voices",
    speed="Speaking speed (1.0 is normal)",
)
@app_commands.autocomplete(name=voice_names)
async def setvoice(
    interaction: discord.Interaction,
    name: str,
    speaker: app_commands.Range[int, 0, 999] = None,
    speed: app_commands.Range[float, 0.5, 2.0] = None,
):
    """Switch voices and play a sample."""
    cog = get_cog(interaction)
    config = interaction.client.config
    await interaction.response.defer(thinking=True)
    old = {key: config.get(key, None) for key in ("tts_voice", "tts_speaker")}
    config.set("tts_voice", name.strip())
    config.set("tts_speaker", speaker)
    if speed is not None:
        config.set("tts_speed", speed)
    try:
        path, _ = await cog.voice.speak_to_file(
            "Hi chat! This is how I sound now. Let's find that shiny!", "sample.wav"
        )
    except Exception as e:
        for key, value in old.items():
            config.set(key, value)
        await interaction.followup.send(f"❌ Kept the old voice: {e}")
        return
    await interaction.followup.send(
        f"🗣️ Voice set to `{name}`" + (f" (speaker {speaker})" if speaker else ""),
        file=discord.File(path),
    )


# -- inspecting ----------------------------------------------------------------


@llm.command(name="log", description="Show the model's recent decisions.")
async def log(interaction: discord.Interaction):
    """List why recent messages were answered, skipped or dropped."""
    cog = get_cog(interaction)
    lines = [f"<t:{int(at)}:T> {text}" for at, text in cog.decisions]
    await interaction.response.send_message(
        embed=make_embed(
            "Recent decisions",
            shorten("\n".join(lines[-25:]) or "Nothing yet.", 4000),
            color=BRAND,
        ),
        allowed_mentions=NONE,
    )


@llm.command(name="chat", description="Show the recent Twitch chat the model sees.")
async def chat(interaction: discord.Interaction):
    """List the buffered clean chat messages."""
    cog = get_cog(interaction)
    count = limit(interaction.client.config, "llm_context_messages", 8)
    lines = [
        f"**{discord.utils.escape_markdown(m['user'])}:** {m['text']}"
        for m in list(cog.recent)[-max(count, 15) :]
    ]
    listening = "listening" if cog.chat_task else "not listening"
    embed = make_embed(
        f"Recent chat ({listening})",
        shorten("\n".join(lines) or "Nothing yet.", 4000),
        color=BRAND,
    )
    embed.set_footer(text=f"The newest {count} are used as context")
    await interaction.response.send_message(embed=embed, allowed_mentions=NONE)


@llm.command(name="prompt", description="Edit the model's persona (system prompt).")
@app_commands.describe(default="Restore the built-in persona instead of editing")
async def prompt(interaction: discord.Interaction, default: bool = False):
    """Open an editor for the system prompt, or restore the default."""
    cog = get_cog(interaction)
    if default:
        interaction.client.config.set("llm_system_prompt", "")
        await interaction.response.send_message("✅ Restored the default persona.")
        return
    await interaction.response.send_modal(
        TextModal(
            "Edit persona",
            "llm_system_prompt",
            "System prompt",
            cog.client.prompt,
            "Who the model is and how it talks",
        )
    )


@llm.command(
    name="sysprompt", description="Show the full system prompt the model gets now."
)
async def sysprompt(interaction: discord.Interaction):
    """Assemble the live system message without asking the model anything."""
    cog = get_cog(interaction)
    await interaction.response.defer(thinking=True)
    messages, parts = await cog.event_prompt()
    system = messages[0]["content"]
    counts = [
        f"{len(parts['lessons'])} lessons",
        f"{len(parts['lines'])} state lines",
        f"{len(parts['facts'])} Pokémon facts",
    ]
    await interaction.followup.send(
        f"{len(system):,} characters, ~{estimate_tokens(messages[:1]):,} tokens · "
        + " · ".join(counts)
        + "\n-# Replies also add memories of the chatter and anyone they name.",
        file=discord.File(io.BytesIO(system.encode()), filename="system_prompt.txt"),
        allowed_mentions=NONE,
    )


@llm.command(name="context", description="Edit notes about the stream and channel.")
async def context(interaction: discord.Interaction):
    """Open an editor for the notes added under the system prompt."""
    await interaction.response.send_modal(
        TextModal(
            "Edit notes",
            "llm_context",
            "Notes",
            get_cog(interaction).client.notes,
            "What the channel is about, running jokes, schedule…",
        )
    )


@llm.command(name="show", description="Show the persona, notes and switches.")
async def show(interaction: discord.Interaction):
    """Show what the model is given and how it's set up."""
    cog = get_cog(interaction)
    client = cog.client
    options = client.options()
    switches = " · ".join(
        f"{name} {'✅' if cog.enabled(name) else '❌'}" for name in SWITCHES
    )
    embeds = [
        make_embed(
            "Persona",
            shorten(client.prompt, 4000),
            color=BRAND,
            fields=[
                ("Switches", switches),
                ("Model", client.model),
                ("Voice", cog.voice.name),
                ("Temperature", options["temperature"]),
                ("Max tokens", options["num_predict"]),
                ("Context window", options["num_ctx"]),
            ],
        ),
        make_embed("Notes", shorten(client.notes or "—", 4000), color=BRAND),
    ]
    await interaction.response.send_message(embeds=embeds, allowed_mentions=NONE)


@llm.command(name="reset", description="Clear the /llm say test conversation.")
@app_commands.describe(
    owner_chat="Also clear your teaching conversation (lessons stay)"
)
async def reset(interaction: discord.Interaction, owner_chat: bool = False):
    """Clear the test conversation so the next `/llm say` starts fresh."""
    get_cog(interaction).sandbox.clear()
    text = "🧹 Test conversation cleared."
    if owner_chat:
        await asyncio.to_thread(interaction.client.database.clear_owner_chat)
        text += " Our teaching conversation too; your lessons are kept."
    await interaction.response.send_message(text)


@llm.command(name="status", description="Check the model server and GPU memory.")
async def status(interaction: discord.Interaction):
    """Report whether Ollama is reachable and how the model is loaded."""
    client = get_cog(interaction).client
    await interaction.response.defer(thinking=True)
    try:
        entry = await client.loaded()
    except LLMError as e:
        await interaction.followup.send(f"❌ {e}")
        return
    if entry is None:
        await interaction.followup.send(
            f"Ollama is running; `{client.model}` loads on the next message."
        )
        return
    size = entry.get("size", 0)
    vram = entry.get("size_vram", 0)
    share = f"{vram / size:.0%}" if size else "?"
    await interaction.followup.send(
        f"✅ `{client.model}` is loaded: {vram / 2**30:.2f} GB in VRAM "
        f"({share} on the GPU)."
    )


__application__ = llm
