"""Describe what's on screen and how the hunt is going, per game.

`describe(state)` turns a state snapshot (see `cynthia.llm.state`) into short
lines for the model. Scene names map to plain descriptions in `SCENES`, and
games add their own lines with `@game_notes(...)`, so new scenes and games
only need an entry here.
"""

# What each CV scene means, as the model should hear it
SCENES = {
    "home": "the Switch HOME menu is open",
    "afk_home": "the Switch HOME menu is open",
    "boot": "the game is starting up",
    "elgato_no_signal": "the capture card has no signal",
    "bdsp_tbox": "a text box is on screen",
    "bdsp_run": "a wild battle is on screen",
    "route_202": "the player is on Route 202",
    "roamer": "the roaming Pokémon is on the map",
    "bdsp_bag": "the bag is open",
}

# Base shiny odds (1 in N) without the Shiny Charm or other boosts
SHINY_ODDS = {
    "Pokémon Brilliant Diamond": 4096,
    "Pokémon Shining Pearl": 4096,
    "Pokémon Sword": 4096,
    "Pokémon Shield": 4096,
    "Pokémon Scarlet": 4096,
    "Pokémon Violet": 4096,
    "Pokémon Legends: Arceus": 4096,
    "Pokémon: Let's Go, Pikachu!": 4096,
    "Pokémon: Let's Go, Eevee!": 4096,
    "Pokémon FireRed Version": 8192,
    "Pokémon LeafGreen Version": 8192,
}

ROAMERS = {"mesprit", "mespirit", "cresselia"}

GAME_NOTES = {}


def game_notes(*titles):
    """Register a function adding lines for the given game titles."""

    def register(func):
        """Add `func(state) -> list[str]` for each title."""
        for title in titles:
            GAME_NOTES.setdefault(title, []).append(func)
        return func

    return register


def duration(seconds):
    """Format seconds as `2h 05m`, `12m` or `40s`."""
    seconds = int(max(seconds, 0))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m" if minutes else f"{secs}s"


def ago(state, at):
    """How long before the snapshot `at` happened, or None."""
    if not at:
        return None
    return duration(state["now"] - at) + " ago"


def odds_lines(state):
    """Odds of having found the shiny by now, for games with known odds."""
    hunt = state["hunt"]
    odds = SHINY_ODDS.get(state["game"]["title"])
    if not odds or not hunt["target"] or not hunt["encounters"]:
        return []
    miss = (1 - 1 / odds) ** hunt["encounters"]
    lines = [
        f"Shiny odds are 1 in {odds:,} per try (no Shiny Charm counted). Chance "
        f"of going {hunt['encounters']:,} tries without a shiny: {miss:.0%}; "
        f"chance one would have shown up by now: {1 - miss:.0%}. " + luck(miss)
    ]
    if hunt["average_seconds"]:
        lines.append(
            "Every try is a fresh roll, so nobody knows how much longer it'll "
            f"take: it could be the next one, but on average it's another {odds:,} "
            f"tries (about {duration(odds * hunt['average_seconds'])} at this pace)."
        )
    return lines


def luck(miss):
    """What the chance of no shiny so far says about the hunt's luck."""
    if miss >= 0.5:
        return "So not having it yet is completely normal."
    if miss >= 0.1:
        return "So the hunt is running a bit unlucky."
    return "So the hunt has been really unlucky."


@game_notes("Pokémon Brilliant Diamond", "Pokémon Shining Pearl")
def bdsp(state):
    """How BDSP hunts work, by hunt type."""
    target = (state["hunt"]["target"] or "").lower()
    if target in ROAMERS:
        return [
            f"{target.title()} is a roaming legendary: the macro keeps "
            "re-encountering it on the same route and checks each one for a "
            "shiny. The whole strategy is the macro and patience."
        ]
    if state["hunt"]["self_encounter"]:
        return ["This is a soft-reset hunt: the bot resets the game for each try."]
    return []


def describe(state):
    """Lines about the game, the screen and the hunt."""
    game = state["game"]
    hunt = state["hunt"]
    lines = []
    if game["screen"] == "no signal":
        lines.append("The Switch isn't showing anything (no capture signal).")
    elif game["title"]:
        where = " (on the HOME menu)" if game["screen"] == "home" else ""
        lines.append(f"Playing {game['title']}{where}.")
    if game["scene"] in SCENES and game["screen"] != "no signal":
        lines.append(f"On screen: {SCENES[game['scene']]}.")
    if hunt["target"]:
        tries = "resets" if hunt["self_encounter"] else "encounters"
        name = hunt["target"].title()
        lines.append(
            f"Hunting shiny {name}: {hunt['encounters']:,} {tries} so far; no "
            f"shiny {name} yet. You don't know about shinies from other hunts."
        )
        if hunt["hunting_seconds"]:
            lines.append(
                f"Hunt time (the hunt's uptime): {duration(hunt['hunting_seconds'])} "
                "of hunting in total, added up across every stream since it "
                "started, not just this one."
            )
        how = "resets the game to meet" if hunt["self_encounter"] else "meets"
        lines.append(
            f"Each {tries[:-1]} (a try) is one time the macro {how} "
            f"{name} and checks whether it's shiny."
        )
        if hunt["average_seconds"]:
            per_hour = 3600 / hunt["average_seconds"]
            lines.append(
                f"Lately one try about every {duration(hunt['average_seconds'])} "
                f"(~{per_hour:.0f} an hour)."
            )
        if hunt["last_encounter"]:
            lines.append(f"Last encounter {ago(state, hunt['last_encounter'])}.")
        if hunt["stopped"]:
            lines.append("The hunt is paused right now.")
        lines += odds_lines(state)
        for func in GAME_NOTES.get(game["title"], []):
            lines += func(state)
    if hunt["shiny_pending"]:
        lines.append(
            "A POSSIBLE SHINY was just found! The hunt is stopped until it's checked."
        )
    return lines
