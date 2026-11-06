"""Basic Pokémon knowledge the chat model can lean on.

A 3B model knows the series only loosely, so facts are looked up here and only
the ones that matter go into the prompt: an overview line, the region of the
game being played, the hunt target, and anything chat brings up by name
(legendaries, mythicals, types, regions and games).
"""

import re

# Attacking type -> (super effective against, not very effective against, no effect)
TYPES = {
    "Normal": ((), ("Rock", "Steel"), ("Ghost",)),
    "Fire": (
        ("Grass", "Ice", "Bug", "Steel"),
        ("Fire", "Water", "Rock", "Dragon"),
        (),
    ),
    "Water": (("Fire", "Ground", "Rock"), ("Water", "Grass", "Dragon"), ()),
    "Electric": (("Water", "Flying"), ("Electric", "Grass", "Dragon"), ("Ground",)),
    "Grass": (
        ("Water", "Ground", "Rock"),
        ("Fire", "Grass", "Poison", "Flying", "Bug", "Dragon", "Steel"),
        (),
    ),
    "Ice": (
        ("Grass", "Ground", "Flying", "Dragon"),
        ("Fire", "Water", "Ice", "Steel"),
        (),
    ),
    "Fighting": (
        ("Normal", "Ice", "Rock", "Dark", "Steel"),
        ("Poison", "Flying", "Psychic", "Bug", "Fairy"),
        ("Ghost",),
    ),
    "Poison": (("Grass", "Fairy"), ("Poison", "Ground", "Rock", "Ghost"), ("Steel",)),
    "Ground": (
        ("Fire", "Electric", "Poison", "Rock", "Steel"),
        ("Grass", "Bug"),
        ("Flying",),
    ),
    "Flying": (("Grass", "Fighting", "Bug"), ("Electric", "Rock", "Steel"), ()),
    "Psychic": (("Fighting", "Poison"), ("Psychic", "Steel"), ("Dark",)),
    "Bug": (
        ("Grass", "Psychic", "Dark"),
        ("Fire", "Fighting", "Poison", "Flying", "Ghost", "Steel", "Fairy"),
        (),
    ),
    "Rock": (("Fire", "Ice", "Flying", "Bug"), ("Fighting", "Ground", "Steel"), ()),
    "Ghost": (("Psychic", "Ghost"), ("Dark",), ("Normal",)),
    "Dragon": (("Dragon",), ("Steel",), ("Fairy",)),
    "Dark": (("Psychic", "Ghost"), ("Fighting", "Dark", "Fairy"), ()),
    "Steel": (
        ("Ice", "Rock", "Fairy"),
        ("Fire", "Water", "Electric", "Steel"),
        (),
    ),
    "Fairy": (("Fighting", "Dragon", "Dark"), ("Fire", "Poison", "Steel"), ()),
}

# Region -> (generation, main games, professor, extra note)
REGIONS = {
    "Kanto": (
        1,
        "Red, Blue and Yellow; remade as FireRed/LeafGreen and "
        "Let's Go, Pikachu!/Eevee!",
        "Professor Oak",
        "",
    ),
    "Johto": (
        2,
        "Gold, Silver and Crystal; remade as HeartGold/SoulSilver",
        "Professor Elm",
        "",
    ),
    "Hoenn": (
        3,
        "Ruby, Sapphire and Emerald; remade as Omega Ruby/Alpha Sapphire",
        "Professor Birch",
        "",
    ),
    "Sinnoh": (
        4,
        "Diamond, Pearl and Platinum; remade as Brilliant Diamond/Shining Pearl",
        "Professor Rowan",
        "Its Champion is Cynthia, whose ace is Garchomp. Legends: Arceus is set "
        "in Hisui, Sinnoh's distant past",
    ),
    "Unova": (5, "Black, White, Black 2 and White 2", "Professor Juniper", ""),
    "Kalos": (6, "X and Y, plus Legends: Z-A", "Professor Sycamore", ""),
    "Alola": (
        7,
        "Sun, Moon, Ultra Sun and Ultra Moon",
        "Professor Kukui",
        "It has island trials instead of gyms",
    ),
    "Galar": (
        8,
        "Sword and Shield, with the Isle of Armor and Crown Tundra expansions",
        "Professor Magnolia",
        "Dynamax and Gigantamax come from here",
    ),
    "Paldea": (
        9,
        "Scarlet and Violet, with the Teal Mask and Indigo Disk expansions",
        "Professor Sada (Scarlet) or Turo (Violet)",
        "It is open world and introduced Terastallizing",
    ),
}

# Ways chat names a game -> (full title, region)
GAMES = {
    "firered": ("Pokémon FireRed", "Kanto"),
    "leafgreen": ("Pokémon LeafGreen", "Kanto"),
    "frlg": ("Pokémon FireRed/LeafGreen", "Kanto"),
    "lets go": ("Pokémon: Let's Go, Pikachu!/Eevee!", "Kanto"),
    "heartgold": ("Pokémon HeartGold", "Johto"),
    "soulsilver": ("Pokémon SoulSilver", "Johto"),
    "hgss": ("Pokémon HeartGold/SoulSilver", "Johto"),
    "emerald": ("Pokémon Emerald", "Hoenn"),
    "omega ruby": ("Pokémon Omega Ruby", "Hoenn"),
    "alpha sapphire": ("Pokémon Alpha Sapphire", "Hoenn"),
    "oras": ("Pokémon Omega Ruby/Alpha Sapphire", "Hoenn"),
    "platinum": ("Pokémon Platinum", "Sinnoh"),
    "brilliant diamond": ("Pokémon Brilliant Diamond", "Sinnoh"),
    "shining pearl": ("Pokémon Shining Pearl", "Sinnoh"),
    "bdsp": ("Pokémon Brilliant Diamond/Shining Pearl", "Sinnoh"),
    "legends arceus": ("Pokémon Legends: Arceus", "Sinnoh"),
    "pla": ("Pokémon Legends: Arceus", "Sinnoh"),
    "black 2": ("Pokémon Black 2", "Unova"),
    "white 2": ("Pokémon White 2", "Unova"),
    "legends z a": ("Pokémon Legends: Z-A", "Kalos"),
    "ultra sun": ("Pokémon Ultra Sun", "Alola"),
    "ultra moon": ("Pokémon Ultra Moon", "Alola"),
    "sword": ("Pokémon Sword", "Galar"),
    "shield": ("Pokémon Shield", "Galar"),
    "swsh": ("Pokémon Sword/Shield", "Galar"),
    "scarlet": ("Pokémon Scarlet", "Paldea"),
    "violet": ("Pokémon Violet", "Paldea"),
}

# Name -> (types, region, "legendary" or "mythical", note)
LEGENDS = {
    "Articuno": (("Ice", "Flying"), "Kanto", "legendary", "one of the legendary birds"),
    "Zapdos": (
        ("Electric", "Flying"),
        "Kanto",
        "legendary",
        "one of the legendary birds",
    ),
    "Moltres": (("Fire", "Flying"), "Kanto", "legendary", "one of the legendary birds"),
    "Mewtwo": (("Psychic",), "Kanto", "legendary", "created from Mew's DNA"),
    "Mew": (("Psychic",), "Kanto", "mythical", "said to know every move"),
    "Raikou": (("Electric",), "Johto", "legendary", "one of the legendary beasts"),
    "Entei": (("Fire",), "Johto", "legendary", "one of the legendary beasts"),
    "Suicune": (("Water",), "Johto", "legendary", "one of the legendary beasts"),
    "Lugia": (("Psychic", "Flying"), "Johto", "legendary", "the mascot of Silver"),
    "Ho-Oh": (("Fire", "Flying"), "Johto", "legendary", "the mascot of Gold"),
    "Celebi": (("Psychic", "Grass"), "Johto", "mythical", "travels through time"),
    "Regirock": (("Rock",), "Hoenn", "legendary", "one of the legendary giants"),
    "Regice": (("Ice",), "Hoenn", "legendary", "one of the legendary giants"),
    "Registeel": (("Steel",), "Hoenn", "legendary", "one of the legendary giants"),
    "Latias": (("Dragon", "Psychic"), "Hoenn", "legendary", "Latios's sister"),
    "Latios": (("Dragon", "Psychic"), "Hoenn", "legendary", "Latias's brother"),
    "Kyogre": (("Water",), "Hoenn", "legendary", "the mascot of Sapphire"),
    "Groudon": (("Ground",), "Hoenn", "legendary", "the mascot of Ruby"),
    "Rayquaza": (("Dragon", "Flying"), "Hoenn", "legendary", "the mascot of Emerald"),
    "Jirachi": (("Steel", "Psychic"), "Hoenn", "mythical", "grants wishes"),
    "Deoxys": (("Psychic",), "Hoenn", "mythical", "came from space"),
    "Uxie": (("Psychic",), "Sinnoh", "legendary", "a lake guardian of knowledge"),
    "Mesprit": (
        ("Psychic",),
        "Sinnoh",
        "legendary",
        "a lake guardian of emotion; it roams after you meet it",
    ),
    "Azelf": (("Psychic",), "Sinnoh", "legendary", "a lake guardian of willpower"),
    "Dialga": (
        ("Steel", "Dragon"),
        "Sinnoh",
        "legendary",
        "rules time; the mascot of Diamond",
    ),
    "Palkia": (
        ("Water", "Dragon"),
        "Sinnoh",
        "legendary",
        "rules space; the mascot of Pearl",
    ),
    "Heatran": (("Fire", "Steel"), "Sinnoh", "legendary", "lives in Stark Mountain"),
    "Regigigas": (("Normal",), "Sinnoh", "legendary", "leader of the legendary giants"),
    "Giratina": (
        ("Ghost", "Dragon"),
        "Sinnoh",
        "legendary",
        "rules the Distortion World; the mascot of Platinum",
    ),
    "Cresselia": (
        ("Psychic",),
        "Sinnoh",
        "legendary",
        "brings good dreams; it roams in Diamond, Pearl, Platinum and BDSP",
    ),
    "Phione": (("Water",), "Sinnoh", "mythical", "hatches from Manaphy's egg"),
    "Manaphy": (("Water",), "Sinnoh", "mythical", "the prince of the sea"),
    "Darkrai": (("Dark",), "Sinnoh", "mythical", "causes nightmares"),
    "Shaymin": (("Grass",), "Sinnoh", "mythical", "has a Sky Forme"),
    "Arceus": (("Normal",), "Sinnoh", "mythical", "said to have shaped the universe"),
    "Victini": (("Psychic", "Fire"), "Unova", "mythical", "brings victory"),
    "Cobalion": (
        ("Steel", "Fighting"),
        "Unova",
        "legendary",
        "one of the Swords of Justice",
    ),
    "Terrakion": (
        ("Rock", "Fighting"),
        "Unova",
        "legendary",
        "one of the Swords of Justice",
    ),
    "Virizion": (
        ("Grass", "Fighting"),
        "Unova",
        "legendary",
        "one of the Swords of Justice",
    ),
    "Tornadus": (("Flying",), "Unova", "legendary", "one of the Forces of Nature"),
    "Thundurus": (
        ("Electric", "Flying"),
        "Unova",
        "legendary",
        "one of the Forces of Nature",
    ),
    "Landorus": (
        ("Ground", "Flying"),
        "Unova",
        "legendary",
        "one of the Forces of Nature",
    ),
    "Reshiram": (("Dragon", "Fire"), "Unova", "legendary", "the mascot of Black"),
    "Zekrom": (("Dragon", "Electric"), "Unova", "legendary", "the mascot of White"),
    "Kyurem": (
        ("Dragon", "Ice"),
        "Unova",
        "legendary",
        "can fuse with Reshiram or Zekrom",
    ),
    "Keldeo": (
        ("Water", "Fighting"),
        "Unova",
        "mythical",
        "the fourth Sword of Justice",
    ),
    "Meloetta": (("Normal", "Psychic"), "Unova", "mythical", "changes form by singing"),
    "Genesect": (("Bug", "Steel"), "Unova", "mythical", "an ancient bug rebuilt"),
    "Xerneas": (("Fairy",), "Kalos", "legendary", "gives life; the mascot of X"),
    "Yveltal": (
        ("Dark", "Flying"),
        "Kalos",
        "legendary",
        "takes life; the mascot of Y",
    ),
    "Zygarde": (
        ("Dragon", "Ground"),
        "Kalos",
        "legendary",
        "watches over the ecosystem",
    ),
    "Diancie": (("Rock", "Fairy"), "Kalos", "mythical", "makes diamonds"),
    "Hoopa": (
        ("Psychic", "Ghost"),
        "Kalos",
        "mythical",
        "summons things through rings",
    ),
    "Volcanion": (("Fire", "Water"), "Kalos", "mythical", "shoots steam"),
    "Type: Null": (("Normal",), "Alola", "legendary", "evolves into Silvally"),
    "Silvally": (("Normal",), "Alola", "legendary", "changes type with memories"),
    "Tapu Koko": (("Electric", "Fairy"), "Alola", "legendary", "guardian of Melemele"),
    "Tapu Lele": (("Psychic", "Fairy"), "Alola", "legendary", "guardian of Akala"),
    "Tapu Bulu": (("Grass", "Fairy"), "Alola", "legendary", "guardian of Ula'ula"),
    "Tapu Fini": (("Water", "Fairy"), "Alola", "legendary", "guardian of Poni"),
    "Cosmog": (("Psychic",), "Alola", "legendary", "evolves into Solgaleo or Lunala"),
    "Solgaleo": (("Psychic", "Steel"), "Alola", "legendary", "the mascot of Sun"),
    "Lunala": (("Psychic", "Ghost"), "Alola", "legendary", "the mascot of Moon"),
    "Necrozma": (("Psychic",), "Alola", "legendary", "the mascot of Ultra Sun/Moon"),
    "Magearna": (
        ("Steel", "Fairy"),
        "Alola",
        "mythical",
        "a machine made 500 years ago",
    ),
    "Marshadow": (("Fighting", "Ghost"), "Alola", "mythical", "hides in shadows"),
    "Zeraora": (("Electric",), "Alola", "mythical", "fast as lightning"),
    "Meltan": (("Steel",), "Kanto", "mythical", "evolves into Melmetal; from Let's Go"),
    "Zacian": (("Fairy",), "Galar", "legendary", "the mascot of Sword"),
    "Zamazenta": (("Fighting",), "Galar", "legendary", "the mascot of Shield"),
    "Eternatus": (("Poison", "Dragon"), "Galar", "legendary", "the source of Dynamax"),
    "Kubfu": (("Fighting",), "Galar", "legendary", "evolves into Urshifu"),
    "Zarude": (("Dark", "Grass"), "Galar", "mythical", "lives in jungle packs"),
    "Regieleki": (("Electric",), "Galar", "legendary", "a newer legendary giant"),
    "Regidrago": (("Dragon",), "Galar", "legendary", "a newer legendary giant"),
    "Glastrier": (("Ice",), "Galar", "legendary", "Calyrex's steed"),
    "Spectrier": (("Ghost",), "Galar", "legendary", "Calyrex's steed"),
    "Calyrex": (
        ("Psychic", "Grass"),
        "Galar",
        "legendary",
        "the king of bountiful harvests",
    ),
    "Enamorus": (("Fairy", "Flying"), "Sinnoh", "legendary", "from Legends: Arceus"),
    "Koraidon": (
        ("Fighting", "Dragon"),
        "Paldea",
        "legendary",
        "the mascot of Scarlet",
    ),
    "Miraidon": (("Electric", "Dragon"), "Paldea", "legendary", "the mascot of Violet"),
    "Wo-Chien": (
        ("Dark", "Grass"),
        "Paldea",
        "legendary",
        "one of the Treasures of Ruin",
    ),
    "Chien-Pao": (
        ("Dark", "Ice"),
        "Paldea",
        "legendary",
        "one of the Treasures of Ruin",
    ),
    "Ting-Lu": (
        ("Dark", "Ground"),
        "Paldea",
        "legendary",
        "one of the Treasures of Ruin",
    ),
    "Chi-Yu": (("Dark", "Fire"), "Paldea", "legendary", "one of the Treasures of Ruin"),
    "Ogerpon": (("Grass",), "Paldea", "legendary", "the masked Pokémon of Kitakami"),
    "Terapagos": (("Normal",), "Paldea", "legendary", "the source of Terastallizing"),
    "Pecharunt": (
        ("Poison", "Ghost"),
        "Paldea",
        "mythical",
        "controls Okidogi and friends",
    ),
}

# Words that show chat is talking about type matchups
TYPE_CUES = re.compile(
    r"\b(types?|weak|weakness|effective|resists?|immune|strong against)\b"
)


def key(text):
    """Lowercase `text` with punctuation turned into single spaces."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def has(haystack, name):
    """Whether keyed `haystack` contains `name` as whole words."""
    return f" {key(name)} " in f" {haystack} "


def weaknesses(types):
    """Attacking types that hit a Pokémon of `types` super effectively."""
    weak = []
    for attacker, (strong, resisted, none) in TYPES.items():
        factor = 1.0
        for defender in types:
            if defender in none:
                factor = 0
            elif defender in strong:
                factor *= 2
            elif defender in resisted:
                factor *= 0.5
        if factor > 1:
            weak.append(f"{attacker} (4x)" if factor >= 4 else attacker)
    return weak


def overview():
    """One line on the series as a whole."""
    regions = ", ".join(f"{name} (Gen {gen})" for name, (gen, *_) in REGIONS.items())
    return (
        f"Pokémon has {len(TYPES)} types and these regions: {regions}. Shiny "
        "Pokémon are rare color variants, usually 1 in 4096 (1 in 8192 before Gen 6)."
    )


def region_line(name):
    """What a region is and which games it's from."""
    gen, games, professor, note = REGIONS[name]
    line = f"{name} is the Gen {gen} region from {games}; its professor is {professor}."
    return f"{line} {note}." if note else line


def legend_line(name):
    """A legendary or mythical Pokémon's type, origin and weaknesses."""
    types, region, kind, note = LEGENDS[name]
    return (
        f"{name} is a {'/'.join(types)} {kind} Pokémon from {region}, {note}; "
        f"weak to {', '.join(weaknesses(types)) or 'nothing'}."
    )


def type_line(name):
    """How a type fares attacking and defending."""
    strong, resisted, none = TYPES[name]
    line = f"{name} type hits {', '.join(strong) or 'nothing'} super effectively"
    if none:
        line += f" and can't touch {', '.join(none)}"
    immune = [a for a, (_, _, no) in TYPES.items() if name in no]
    line += f"; it's weak to {', '.join(weaknesses([name]))}"
    if immune:
        line += f" and immune to {', '.join(immune)}"
    return line + "."


def region_of_game(title):
    """The region of a game title like "Pokémon Brilliant Diamond", or None."""
    title = key(title or "")
    for alias, (_, region) in GAMES.items():
        if has(title, alias):
            return region
    for name, (_, games, _, _) in REGIONS.items():
        names = [g.strip() for g in re.split(r",|;| and |/", games)]
        if any(has(title, g) for g in names if len(g) > 2):
            return name
    return None


def facts(texts=(), game=None, target=None, count=6):
    """Up to `count` fact lines for the game, hunt target and things named in `texts`.

    The overview always comes first and doesn't count toward `count`.
    """
    lines = []

    def add(line):
        if line not in lines:
            lines.append(line)

    region = region_of_game(game)
    if region:
        add(region_line(region))
    target_key = key(target or "")
    for name in LEGENDS:
        if target_key and has(target_key, name):
            add(legend_line(name))
    said = key(" ".join(texts))
    if said:
        for name in LEGENDS:
            if has(said, name):
                add(legend_line(name))
        for name in REGIONS:
            if has(said, name):
                add(region_line(name))
        for alias, (title, region) in GAMES.items():
            if has(said, alias):
                add(f"{title} is set in {region}.")
        if TYPE_CUES.search(said):
            for name in TYPES:
                if has(said, name):
                    add(type_line(name))
    return [overview(), *lines[:count]]
