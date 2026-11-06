"""Chatters' pronouns, only from what chat says outright.

Everyone is "they" until there's evidence: a chatter stating their own
pronouns, or several people consistently using one set for them. Evidence is
found with fixed patterns (never the model) and kept with the message that
showed it, so every conclusion can be checked.
"""

import re

SETS = {"he": "he/him", "she": "she/her", "they": "they/them"}
WORDS = {
    "he": "he",
    "him": "he",
    "his": "he",
    "himself": "he",
    "she": "she",
    "her": "she",
    "hers": "she",
    "herself": "she",
    "they": "they",
    "them": "they",
    "their": "they",
    "theirs": "they",
    "themself": "they",
    "themselves": "they",
}
PRONOUN = r"(he|she|they)\s*/\s*(him|his|her|hers|them|they|he|she|it|any)"
# "my pronouns are she/her", "I use he/him", "I go by they/them", "(she/her)"
STATED = re.compile(
    rf"(?:\bpronouns?\b[^/]{{0,20}}?|\bi\s+(?:use|go\s+by|prefer)\s+|^\(?\s*)"
    rf"\b{PRONOUN}\b",
    re.I,
)
# "my pronouns are she" / "I'm a he"
STATED_SINGLE = re.compile(
    r"(?:\bmy\s+pronouns?\s+(?:are|is|r)|\bi(?:'?m|\s+am)\s+an?)\s+(he|she|they)\b",
    re.I,
)
TOKEN = re.compile(r"@?[A-Za-z0-9_']+")
# A message speaking to someone uses "you"; its "she"/"he" is someone else
SECOND_PERSON = {"you", "your", "you're", "youre", "u", "ur", "yours"}
# Evidence needed before others' references settle someone's pronouns
MIN_REFERENCES = 3
MIN_REFERRERS = 2
AGREEMENT = 0.8


def stated(text):
    """The pronoun set (`he`, `she` or `they`) a chatter states for themselves.

    Not when the message says "you", as in asking someone else's pronouns.
    """
    if SECOND_PERSON & {w.lower() for w in TOKEN.findall(text)}:
        return None
    match = STATED.search(text) or STATED_SINGLE.search(text)
    return match.group(1).lower() if match else None


def name_index(names):
    """`names` (lowercase name -> login) plus unique short forms like "fish".

    The part before an underscore counts when it's 4+ letters and no other
    chatter shares it.
    """
    index = dict(names)
    short = {}
    for login in set(names.values()):
        part = login.split("_")[0]
        if len(part) >= 4 and part != login:
            short.setdefault(part, set()).add(login)
    for part, logins in short.items():
        if len(logins) == 1 and part not in index:
            index[part] = next(iter(logins))
    return index


def referenced(text, speaker, names, bot_names=()):
    """`(login, set)` when `text` talks about one chatter using one pronoun set.

    Strict on purpose: exactly one other known chatter is named, not at the
    start (that's talking to them), the bot isn't named, the message doesn't
    say "you", and every third-person pronoun after the name is from one set.
    """
    tokens = TOKEN.findall(text)
    lowered = [t.lower().lstrip("@").rstrip(",:") for t in tokens]
    if not lowered or SECOND_PERSON & set(lowered):
        return None
    bots = {name.lower() for name in bot_names}
    if bots & set(lowered):
        return None
    targets = {}
    for i, word in enumerate(lowered):
        login = names.get(word)
        if login and login != speaker.lower() and login not in bots:
            targets.setdefault(login, i)
    if len(targets) != 1:
        return None
    ((login, at),) = targets.items()
    if at == 0:
        return None
    found = {WORDS[w] for w in lowered[at + 1 :] if w in WORDS}
    if len(found) != 1:
        return None
    return login, found.pop()


def settled(evidence):
    """`(set, why)` once the evidence is clear, else None.

    `evidence` rows have `pronouns`, `kind` (`self` or `reference`) and
    `by_login`. A chatter's own latest statement wins; otherwise at least
    `MIN_REFERENCES` references from `MIN_REFERRERS` people, `AGREEMENT` of
    them using the same set.
    """
    own = [row for row in evidence if row["kind"] == "self"]
    if own:
        return own[-1]["pronouns"], "they said so"
    refs = [row for row in evidence if row["kind"] == "reference"]
    if len(refs) < MIN_REFERENCES:
        return None
    counts = {}
    for row in refs:
        counts[row["pronouns"]] = counts.get(row["pronouns"], 0) + 1
    top = max(counts, key=counts.get)
    people = {row["by_login"] for row in refs if row["pronouns"] == top}
    if counts[top] / len(refs) < AGREEMENT or len(people) < MIN_REFERRERS:
        return None
    return top, f"{len(people)} people refer to them that way"


def describe(evidence):
    """`pronouns she/her (they said so)`, or None while unknown."""
    found = settled(evidence)
    if found is None:
        return None
    pronouns, why = found
    return f"pronouns {SETS[pronouns]} ({why})"
