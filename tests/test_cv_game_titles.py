import pytest

from cynthia.daemons.cv import HomeGameTitle, canonical_game_title


@pytest.mark.parametrize(
    "ocr_text,title",
    [
        ("Pokémon HOME", "Pokémon HOME"),
        ("Pokemon: Lets Go, Pikachu!", "Pokémon: Let's Go, Pikachu!"),
        ("Pokemon: Let's Go Eevee!", "Pokémon: Let's Go, Eevee!"),
        ("Pokemon Legends Arceus", "Pokémon Legends: Arceus"),
        ("Pokemon Legends Z A", "Pokémon Legends: Z-A"),
        ("Pokemon Scarlet", "Pokémon Scarlet"),
        ("Pokemon Violet", "Pokémon Violet"),
        ("Pokemon Sword", "Pokémon Sword"),
        ("Pokemon Shield", "Pokémon Shield"),
        ("Pokemon Brilliant Diamond", "Pokémon Brilliant Diamond"),
        ("Pokemon Shining Pearl", "Pokémon Shining Pearl"),
        ("Pokémon FireRed Version", "Pokémon FireRed Version"),
        ("Pokemon Fire Red Version", "Pokémon FireRed Version"),
        ("Pokemon FireRed", "Pokémon FireRed Version"),
        ("Pokemon Fire Red", "Pokémon FireRed Version"),
        ("Pokémon LeafGreen Version", "Pokémon LeafGreen Version"),
        ("Pokemon Leaf Green Version", "Pokémon LeafGreen Version"),
        ("Pokemon LeafGreen", "Pokémon LeafGreen Version"),
        ("Pokemon Leaf Green", "Pokémon LeafGreen Version"),
    ],
)
def test_canonical_game_title_normalizes_ocr_punctuation_and_accents(ocr_text, title):
    assert canonical_game_title(ocr_text) == title


def test_canonical_game_title_corrects_ocr_typo():
    assert canonical_game_title("Pokémon Scerlet") == "Pokémon Scarlet"


def test_canonical_game_title_preserves_unknown_text():
    assert canonical_game_title("Unknown Game") == "Unknown Game"


@pytest.mark.parametrize(
    "text",
    [
        "Super Nintendo Entertainment System – Nintendo Classics",
        "Super Nintendo Entertainment System – Nintendo Switch Online",
        "Super Nintendo Entertainment System –",
        "Sper Nintendo Entertainment System",
        "ntendo Classics Super Nintendo Ent",
        "Pokémon Brilliant",
        "illiant Diamond",
    ],
)
def test_scrolling_titles_resolve_distinctive_fragments_and_omit_branding(text):
    expected = (
        "Pokémon Brilliant Diamond"
        if "Diamond" in text or "Brilliant" in text
        else "Super Nintendo Entertainment System"
    )
    assert canonical_game_title(text) == expected


@pytest.mark.parametrize(
    "text", ["Entertainment System", "Pokémon Legends", "Nintendo"]
)
def test_shared_title_fragments_are_not_guessed(text):
    assert canonical_game_title(text) == text


def test_home_title_stays_stable_through_the_observed_scroll_cycle():
    reader = HomeGameTitle()
    expected = "Super Nintendo Entertainment System"
    assert reader.read(expected, 0) == expected
    for now, text in enumerate(
        [
            "o Entertainment System – Nintendo Classics",
            "ntendo Classics Super Nintendo Ent",
            "Nintendo Entertainment System",
            "Super Nintendo Entertainment System –",
            "Nintendo Classics",
            "intendo Classics",
        ],
        1,
    ):
        assert reader.read(text, now) == expected


@pytest.mark.parametrize(
    "branding", ["Nintendo Class", "Nintendo  Class", "Nintendo\nClass"]
)
def test_actual_home_screen_ocr_keeps_the_name_when_branding_is_clipped(branding):
    reader = HomeGameTitle()
    for now, text in enumerate(
        [
            "Super Nintendo Entertainment System - 1",
            f"o Entertainment System - {branding}",
            "ntendo Classics\nSuper Nintendo Ent",
        ]
    ):
        assert reader.read(text, now) == "Super Nintendo Entertainment System"


def test_new_selection_replaces_a_previous_scrolling_title_after_settling():
    reader = HomeGameTitle()
    old = reader.read("Super Nintendo Entertainment System", 0)
    assert reader.read("Nintendo Entertainment System", 1) == old
    assert reader.read("Nintendo Entertainment System", 1.5) == old
    assert (
        reader.read("Nintendo Entertainment System", 2)
        == "Nintendo Entertainment System"
    )
    assert reader.read("Unknown Game", 3) == "Unknown Game"


def test_scrape_text_falls_back_to_paddleocr_2x(monkeypatch):
    import numpy

    from cynthia.daemons import cv

    class Legacy:
        def ocr(self, image, cls=True):
            return [[[None, ("Pokemon Sword", 0.9)]]]

    monkeypatch.setattr(cv, "ocr", Legacy())
    frame = numpy.zeros((10, 10, 3), dtype=numpy.uint8)
    assert cv.CV.scrape_text(frame, w=10, h=10) == "Pokemon Sword"
