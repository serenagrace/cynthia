"""Catch replies that repeat what the bot said recently or loop on a phrase."""

import re

from rapidfuzz import fuzz

WORDS = re.compile(r"[a-z0-9']+")


def normalize(text):
    """Lowercase words only, so punctuation and emotes don't hide a repeat."""
    return " ".join(WORDS.findall(text.lower()))


def loops(text, size=3, times=3):
    """Whether any `size`-word phrase appears `times` or more in `text`."""
    words = normalize(text).split()
    counts = {}
    for i in range(len(words) - size + 1):
        phrase = tuple(words[i : i + size])
        counts[phrase] = counts.get(phrase, 0) + 1
        if counts[phrase] >= times:
            return True
    return False


def similar(text, said, threshold=0.8):
    """The earlier message `text` is too close to, or None."""
    candidate = normalize(text)
    if not candidate:
        return None
    for earlier in reversed(list(said)):
        if fuzz.ratio(candidate, normalize(earlier)) / 100 >= threshold:
            return earlier
    return None


def repeats(text, earlier, threshold=0.8):
    """How many of the `earlier` texts `text` is nearly the same as."""
    candidate = normalize(text)
    if not candidate:
        return 0
    return sum(
        1
        for other in earlier
        if fuzz.ratio(candidate, normalize(other)) / 100 >= threshold
    )
