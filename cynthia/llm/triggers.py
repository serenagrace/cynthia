"""Decide which chat messages and stream events the chat model answers.

Every chance and cooldown comes from the bot config, so they can be tuned
with `/cset` while the bot runs.
"""

import random
import re
import time
from collections import deque

from rapidfuzz import fuzz

from .client import setting

QUESTION = re.compile(
    r"\?\s*$|^(who|what|when|where|why|how|is|are|do|does|did|can|could|will|"
    r"would|should|have|has)\b",
    re.I,
)
WORD = re.compile(r"[a-z0-9']+", re.I)
# Whole names as typed, underscores included ("@Cynthia__Bot")
NAME = re.compile(r"[a-z0-9_']+", re.I)
AT_NAME = re.compile(r"@(\w+)")
# "ash: ..." or "ash, ..." at the start of a message
LEAD_NAME = re.compile(r"^\s*@?(\w+)\s*[:,]")

# Defaults for each kind of message, as `llm_reply_<kind>_chance`. A followup
# is a question from someone the bot just answered.
REPLY_CHANCES = {
    "mention": 1.0,
    "followup": 1.0,
    "question": 0.5,
    "short": 0.03,
    "random": 0.05,
}
# Kinds addressed to the bot: only short cooldowns apply
ADDRESSED = ("mention", "followup")
# Defaults for each kind of event, as `llm_event_<kind>_chance`
EVENT_CHANCES = {
    "shiny": 1.0,
    "watchdog": 0.75,
    "failsafe": 0.5,
    "encounter": 0.05,
    "idle": 1.0,
}
SUBSTANTIVE_WORDS = 4
# How long a chatter's name is recognized at the start of a message
ADDRESSEE_SECONDS = 1800


def chance(config, key, default):
    """A probability setting clamped to 0..1."""
    try:
        return min(max(float(setting(config, key, default)), 0.0), 1.0)
    except (TypeError, ValueError):
        return default


def names_list(config, key, default):
    """A list setting of lowercase names; accepts a comma-separated string."""
    value = setting(config, key, default)
    if isinstance(value, str):
        value = value.split(",")
    return [str(v).strip().lstrip("@").lower() for v in value if str(v).strip()]


def bot_names(config):
    """Names chat uses for the bot."""
    return names_list(config, "llm_bot_names", ["cynthia"])


def ignored(config, login):
    """Whether messages from `login` are never read or answered."""
    default = ["streamelements", "nightbot", "streamlabs", "moobot"]
    return (login or "").lower() in names_list(config, "llm_ignored_chatters", default)


def names_me(word, names):
    """Whether `word` is one of the bot's names, allowing "'s", plurals and typos."""
    word = word.lower().strip("'")
    for suffix in ("'s", "s"):
        if word.endswith(suffix) and word[: -len(suffix)] in names:
            return True
    if word in names:
        return True
    # A one-letter slip ("cyntia", "cynthai") still counts for longer names
    return any(
        len(name) >= 5 and len(word) >= 4 and fuzz.ratio(word, name) >= 85
        for name in names
    )


# A parenthesized part, or an unclosed one running to the end ("(jk"); a
# parenthesis must open onto a word, so ":(" and "(:" stay
ASIDE = re.compile(r"[(（]\s*\w[^()（）]*(?:[)）]|$)")


def heard(text):
    """`text` without its (parenthesized) parts, which the bot never hears."""
    return " ".join(ASIDE.sub(" ", text).split())


def aside(text):
    """Whether all of `text` is in parentheses: chat the bot shouldn't hear."""
    return bool(text.strip()) and not heard(text)


def classify(config, text, extra_names=(), reply_to=None):
    """Kind of message: mention, question, short, random (substantive), or None.

    Naming the bot (`llm_bot_names` plus `extra_names`, like the channel login)
    or replying to its message is a mention. Commands (`!uptime`) are never
    answered.
    """
    text = text.strip()
    if not text or text.startswith("!") or aside(text):
        return None
    names = set(bot_names(config)) | {n.lower() for n in extra_names if n}
    if reply_to and reply_to.lower() in names:
        return "mention"
    words = [w.lower() for w in WORD.findall(text)]
    tags = [w.lower().strip("_") for w in NAME.findall(text)]
    if any(names_me(word, names) for word in {*words, *tags}):
        return "mention"
    if QUESTION.search(text):
        return "question"
    if len(words) >= SUBSTANTIVE_WORDS:
        return "random"
    return "short" if words else None


def addressed_elsewhere(text, names, reply_to=None, chatters=()):
    """Whether a message is aimed at someone other than the bot.

    It is when it replies to or @-mentions someone else, or opens with the
    name of someone in `chatters` ("ash: nice"). `names` are the bot's names.
    """
    names = {n.lower() for n in names if n}
    if reply_to and reply_to.lower() not in names:
        return True
    if any(not names_me(name, names) for name in AT_NAME.findall(text)):
        return True
    lead = LEAD_NAME.match(text)
    return bool(lead) and lead.group(1).lower() in {c.lower() for c in chatters}


class Triggers:
    """Roll the configured chances, respecting cooldowns."""

    def __init__(self, config, rng=None, clock=time.monotonic):
        """Use `config` for chances; `rng` and `clock` are swappable for tests."""
        self.config = config
        self.rng = rng or random.Random()
        self.clock = clock
        self.last_reply = None
        self.last_event = None
        self.last_user = {}
        self.mentions = deque()
        # When she posted lately, for the hard caps (see `over_limit`)
        self.posts = deque()
        self.pause = None
        self.started = clock()
        # (time, login) of recent messages, to tell how busy chat is
        self.chatters = deque()
        # login -> when they last chatted, to tell who a message is aimed at
        self.seen = {}
        self.decision = {}

    def seconds(self, key, default):
        """A cooldown setting in seconds."""
        return float(setting(self.config, key, default))

    def cooling(self, last, key, default):
        """Whether a cooldown that began at `last` is still running."""
        return last is not None and self.clock() - last < self.seconds(key, default)

    def message(
        self, login, text, repeats=0, extra_names=(), reply_to=None, streamer=None
    ):
        """Return the kind of message if it should be answered, else None.

        The chance rises the quieter chat is and the longer the bot has been
        silent (see `boost`), and a little for the `streamer`'s own messages,
        unless the message is aimed at someone else. The streamer's questions
        use `llm_streamer_question_chance` (default certain) instead. Each of `repeats` (recent
        near-identical messages) cuts it by `llm_repeat_input_factor`. The
        streamer skips every cooldown; only the chance applies to them.
        """
        kind = classify(self.config, text, extra_names, reply_to)
        # Why the last message was or wasn't answered, for the chat journal
        self.decision = {"kind": kind}
        if kind is None or ignored(self.config, login):
            self.decision["skip"] = (
                "ignored" if kind else "aside" if aside(text) else "not answerable"
            )
            return None
        now = self.clock()
        self.seen = {
            name: at for name, at in self.seen.items() if now - at <= ADDRESSEE_SECONDS
        }
        others = set(self.seen) - {login.lower()}
        self.seen[login.lower()] = now
        chatters = self.count_chatter(login)
        names = set(bot_names(self.config)) | set(extra_names)
        elsewhere = addressed_elsewhere(text, names, reply_to, others)
        if kind == "question" and self.cooling(
            self.last_user.get(login.lower()), "llm_followup_seconds", 90
        ):
            kind = "followup"
        owner = bool(streamer) and login.lower() == streamer.lower()
        spam = self.mention_spam() if kind in ADDRESSED and not owner else 0
        # Every reply waits out the overall cooldown; other kinds wait longer
        self.decision.update(kind=kind, elsewhere=elsewhere, chatters=chatters)
        cooldown = None if owner else self.cooldown(login, kind)
        if cooldown:
            self.decision["skip"] = cooldown
            return None
        limit = self.over_limit()
        if limit:
            self.decision["skip"] = limit
            return None
        odds = chance(self.config, f"llm_reply_{kind}_chance", REPLY_CHANCES[kind])
        if owner and kind == "question" and not elsewhere:
            # The streamer's questions are hers to answer, not left to luck
            odds = max(odds, chance(self.config, "llm_streamer_question_chance", 1.0))
        # Short messages ("lol", "gg") rarely need an answer, however quiet it
        # is, and talk aimed at someone else isn't the bot's to join
        if kind not in ("short", *ADDRESSED) and not elsewhere:
            odds += (1 - odds) * self.boost(chatters)
            if owner:
                odds += (1 - odds) * chance(self.config, "llm_streamer_boost", 0.15)
        odds *= chance(self.config, "llm_repeat_input_factor", 0.3) ** repeats
        odds *= chance(self.config, "llm_mention_spam_factor", 0.5) ** spam
        roll = self.rng.random()
        self.decision.update(odds=round(odds, 3), roll=round(roll, 3))
        if roll >= odds:
            self.decision["skip"] = "chance"
            return None
        return kind

    def cooldown(self, login, kind):
        """The cooldown keeping a `kind` message from `login` unanswered, if any."""
        # Talk aimed at her waits out the pause (see `wait`) instead
        if kind not in ADDRESSED and self.wait():
            return "overall pause"
        if kind not in ADDRESSED and self.cooling(
            self.last_reply, "llm_reply_cooldown_seconds", 30
        ):
            return "reply cooldown"
        # Being named keeps only a short per-user cooldown to stop spamming
        key, default = (
            ("llm_mention_cooldown_seconds", 5)
            if kind in ADDRESSED
            else ("llm_user_cooldown_seconds", 20)
        )
        if self.cooling(self.last_user.get(login.lower()), key, default):
            return "user cooldown"
        return None

    def wait(self):
        """Seconds left of the pause since she last spoke (0 when it's over)."""
        if self.last_reply is None or self.pause is None:
            return 0
        return max(self.last_reply + self.pause - self.clock(), 0)

    def over_limit(self):
        """Which hard cap on her posts is reached, if any.

        At most `llm_max_posts_per_minute` posts in any minute and
        `llm_max_posts_per_10_minutes` in any ten, whoever she's answering;
        0 turns a cap off.
        """
        now = self.clock()
        while self.posts and now - self.posts[0] >= 600:
            self.posts.popleft()
        for key, default, span in (
            ("llm_max_posts_per_minute", 4, 60),
            ("llm_max_posts_per_10_minutes", 20, 600),
        ):
            cap = int(self.seconds(key, default))
            if cap > 0 and sum(now - t < span for t in self.posts) >= cap:
                return f"{key} cap"
        return None

    def count_chatter(self, login):
        """Note a message from `login`; return how many people chatted lately.

        Lately is the last `llm_quiet_window_seconds`, including this message.
        """
        now = self.clock()
        window = self.seconds("llm_quiet_window_seconds", 180)
        while self.chatters and now - self.chatters[0][0] > window:
            self.chatters.popleft()
        self.chatters.append((now, login.lower()))
        return len({name for _, name in self.chatters})

    def boost(self, chatters):
        """How far (0..1) to raise a reply chance towards certain.

        A quiet chat counts fully with one chatter and not at all with
        `llm_busy_chatters` or more. Silence grows to full over
        `llm_silence_boost_seconds` since the bot last spoke. Either can be
        turned off by setting it to 0.
        """
        busy = self.seconds("llm_busy_chatters", 5)
        quiet = min(max((busy - chatters) / (busy - 1), 0), 1) if busy > 1 else 0
        span = self.seconds("llm_silence_boost_seconds", 900)
        last = self.last_reply if self.last_reply is not None else self.started
        silent = min((self.clock() - last) / span, 1) if span > 0 else 0
        return 1 - (1 - quiet) * (1 - silent)

    def mention_spam(self):
        """Count this mention and return how many came just before it.

        Mentions from anyone within `llm_mention_window_seconds`, past the
        first `llm_mention_spam_free`, each cut the reply chance by
        `llm_mention_spam_factor`. The streamer's aren't counted.
        """
        now = self.clock()
        window = self.seconds("llm_mention_window_seconds", 60)
        while self.mentions and now - self.mentions[0] > window:
            self.mentions.popleft()
        free = int(self.seconds("llm_mention_spam_free", 2))
        earlier = max(len(self.mentions) - free, 0)
        self.mentions.append(now)
        return earlier

    def event(self, kind):
        """Whether to talk about a stream event of `kind`."""
        if kind != "shiny" and self.over_limit():
            return False
        if kind != "shiny" and self.cooling(
            self.last_event, "llm_event_cooldown_seconds", 60
        ):
            return False
        if kind != "shiny" and self.cooling(
            self.last_reply, "llm_reply_cooldown_seconds", 30
        ):
            return False
        odds = chance(self.config, f"llm_event_{kind}_chance", EVENT_CHANCES[kind])
        return self.rng.random() < odds

    def next_pause(self):
        """Seconds before any next reply, drawn from a bell curve.

        Normal around `llm_reply_min_seconds` with spread
        `llm_reply_jitter_seconds`, kept within a third to three times the mean.
        """
        mean = self.seconds("llm_reply_min_seconds", 9)
        spread = self.seconds("llm_reply_jitter_seconds", 2.5)
        return min(max(self.rng.gauss(mean, spread), mean / 3), mean * 3)

    def spoke(self, login=None, event=False):
        """Start the cooldowns after the bot says something."""
        now = self.clock()
        self.last_reply = now
        self.posts.append(now)
        self.pause = self.next_pause()
        if event:
            self.last_event = now
        if login:
            self.last_user[login.lower()] = now

    def idle_seconds(self):
        """Seconds without saying anything before an idle remark."""
        return float(setting(self.config, "llm_idle_minutes", 20)) * 60
