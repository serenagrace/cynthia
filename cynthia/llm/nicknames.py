"""Nicknames chat uses for people, found by fuzzy-matching present chatters.

A word in a message is a nickname candidate when it looks like exactly one
other chatter who is around right now ("fish" for fish_vtuber, "sky" for
theinfinitesky, "fishy" for fish_vtuber). Common words never count, and a
candidate becomes a nickname only after `MIN_USES` uses.
"""

import re

from rapidfuzz import fuzz

MIN_USES = 3
# Shortest word that can be a nickname
MIN_LENGTH = 3
# Short candidates must begin or end a part of the name; longer ones may be
# fuzzy ("fishy" for fish_vtuber)
SHORT = 4
FUZZY_MATCH = 80
WORD = re.compile(r"@?[A-Za-z][A-Za-z0-9_]*")
COMMON = set("""the and for are but not you all any can had her was one our out day get
    has him his how man new now old see two way who boy did its let put say she
    too use that with have this will your from they know want been good much
    some time very when come here just like long make many more only over such
    take than them well were what where which while would there their these
    those then thing think about after again also back because before being
    could down even every first going great into little look made most never
    other people right said same should still through under until very where
    while world year yeah yes yep nope okay lol lmao omg wow nice cool gg hype
    pog poggers kekw true real game games play playing shiny hunt hunting
    stream chat chatting channel bot mom dad hey hello hiya bye thanks thank
    please sorry love cute funny""".split())


def parts(login):
    """A login's pieces: split on underscores and digits ("fish", "vtuber")."""
    return [p for p in re.split(r"[_0-9]+", login.lower()) if p]


def looks_like(word, login):
    """Whether `word` could be a nickname for `login` (and isn't the login)."""
    word, login = word.lower(), login.lower()
    plain = login.replace("_", "")
    if len(word) < MIN_LENGTH or word in (login, plain):
        return False
    if len(word) <= SHORT:
        return any(
            p.startswith(word) or (p.endswith(word) and len(p) > len(word))
            for p in parts(login)
        )
    if word in plain:
        return True
    return word[0] == plain[0] and fuzz.partial_ratio(word, plain) >= FUZZY_MATCH


def candidates(text, speaker, present, known=()):
    """`(nickname, login)` pairs in `text` for chatters in `present`.

    `known` names (logins, display names, nicknames already in use) are
    skipped, as is anything that could mean more than one present chatter.
    """
    speaker = speaker.lower()
    others = [login.lower() for login in present if login.lower() != speaker]
    known = {name.lower() for name in known}
    found = []
    for match in WORD.finditer(text):
        word = match.group(0).lstrip("@").lower().rstrip("_")
        if word in known or word in COMMON:
            continue
        matches = [login for login in others if looks_like(word, login)]
        if len(matches) == 1 and (word, matches[0]) not in found:
            found.append((word, matches[0]))
    return found


# A reply word made of a name plus this much more is a garbled name
# ("serenachannel"); shorter additions are endings ("serenas", "fishy")
GARBLE_EXTRA = 4
GARBLE_NAME = 5


def garbled(text, names):
    """The first word in `text` that fuses a known name with something else.

    `names` are names chat uses for people; a word that is itself one of
    them (or a login without underscores) is fine.
    """
    names = {n.lower() for n in names}
    plain = {n.replace("_", "") for n in names}
    for match in WORD.finditer(text):
        word = match.group(0).lstrip("@").lower()
        if word in names or word in plain:
            continue
        for name in plain:
            if len(name) < GARBLE_NAME or len(word) < len(name) + GARBLE_EXTRA:
                continue
            if word.startswith(name) or word.endswith(name):
                return word
    return None
