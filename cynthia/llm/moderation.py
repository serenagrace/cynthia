"""Filter chat that breaks Twitch's rules, curses, or is sexual, coming in or going out.

Profanity, slurs and sexual terms come from better-profanity's word list,
which also catches common letter substitutions. Patterns below add threats and
self-harm, personal information, links, and attempts to steer the model.
"""

import re

from better_profanity import Profanity

# Harassment and self-harm phrasing the word list doesn't cover
TOS_PATTERNS = [
    r"\bk+\s*y+\s*s+\b",
    r"\bkill\s*(?:ur|your)\s*self\b",
    r"\bunalive\b",
    r"\b(?:hope|wish)\s+(?:you|u)\s+(?:die|get\s+cancer)\b",
    r"\b(?:neck|hang)\s+(?:yourself|urself)\b",
    r"\bi(?:'?ll| will| am going to| gonna)\s+(?:kill|hurt|find)\s+(?:you|u)\b",
    r"\bswat(?:ting)?\b",
    r"\bdox+(?:x|ing|ed)?\b",
    r"\bf+a+p+\b",
    r"\bcoom\w*\b",
    r"\bnude?s\b",
    r"\bonlyfans\b",
]
PERSONAL_PATTERNS = [
    # Phone numbers
    r"(?<!\d)(?:\+?\d[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)",
    # Email addresses
    r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b",
    # IPv4 addresses
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    # Street addresses
    r"\b\d{1,5}\s+\w+(?:\s+\w+)?\s+(?:st|street|ave|avenue|rd|road|blvd|lane|ln|dr|drive)\b",
]
LINK_PATTERN = r"(?:https?://|www\.)\S+|\b\w+\.(?:com|net|org|gg|tv|ly|io|xyz)\b"
# Chatters trying to rewrite the model's instructions
STEERING_PATTERNS = [
    r"\bignore\s+(?:all\s+|any\s+)?(?:previous|prior|above|your|the)\b.*\b(?:instructions|rules|prompt)",
    r"\b(?:system|developer)\s+(?:prompt|message|instructions)\b",
    r"\byou\s+are\s+now\b",
    r"\bnew\s+(?:instructions|rules|persona)\b",
    r"\bpretend\s+(?:to\s+be|you\s+are)\b",
    r"\bjailbreak\b",
]


def compile_all(patterns):
    """Compile case-insensitive patterns."""
    return [re.compile(pattern, re.I) for pattern in patterns]


class Moderator:
    """Classify text as clean (None) or by the first rule it breaks."""

    def __init__(self, allow=(), block=()):
        """Load the word list, minus `allow` words and plus `block` words."""
        self.profanity = Profanity()
        self.profanity.load_censor_words(
            whitelist_words=[word.lower() for word in allow]
        )
        if block:
            self.profanity.add_censor_words([word.lower() for word in block])
        self.tos = compile_all(TOS_PATTERNS)
        self.personal = compile_all(PERSONAL_PATTERNS)
        self.link = re.compile(LINK_PATTERN, re.I)
        self.steering = compile_all(STEERING_PATTERNS)

    def check(self, text, outgoing=False):
        """Return why `text` isn't allowed, or None when it's fine.

        Incoming chat also rejects attempts to steer the model; outgoing replies
        also reject links, since the model should never post them.
        """
        if any(pattern.search(text) for pattern in self.tos):
            return "tos"
        if self.profanity.contains_profanity(text):
            return "profanity"
        if any(pattern.search(text) for pattern in self.personal):
            return "personal info"
        if outgoing and self.link.search(text):
            return "link"
        if not outgoing and any(pattern.search(text) for pattern in self.steering):
            return "steering"
        return None


# Why each rule exists, as told to the owner and to the model
EXPLANATIONS = {
    "tos": "it touched on self-harm, violence, hate or other things against "
    "Twitch's rules",
    "profanity": "it had swearing, slurs or sexual words",
    "personal info": "it looked like personal information (an address, phone "
    "number or email)",
    "link": "it had a link, and the bot never posts links",
    "steering": "it tried to give the bot instructions",
    "repetition": "it repeated something said recently or looped on a phrase",
    "third person": "it talked about the person you were answering (or mom, "
    "while answering mom) as someone else instead of saying 'you'",
    "made up": "it said mom said, did or wants something; never put things "
    "on mom, say it in your own words",
    "doubt": "it doubted or snarked at something mom told you; trust her",
}
# Lessons the owner can turn a blocked reply into
LESSONS = {
    "tos": "Never joke about self-harm, violence or hate, even playfully.",
    "profanity": "Never swear or use crude, sexual or insulting words, even "
    "jokingly or when quoting chat.",
    "personal info": "Never share or repeat addresses, phone numbers, emails or "
    "other personal details.",
    "link": "Never post links or web addresses.",
    "repetition": "Don't repeat yourself; say something new or vary how you " "say it.",
}


def explain(reason):
    """Plain-language reason a message was blocked."""
    return EXPLANATIONS.get(reason, f"it broke the {reason} rule")


def culprits(moderator, text):
    """Words in `text` the profanity list objects to."""
    words = []
    for word in re.findall(r"[\w'*@$!]+", text):
        if word.lower() not in words and moderator.profanity.contains_profanity(word):
            words.append(word.lower())
    return words
