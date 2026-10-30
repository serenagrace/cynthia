import pytest

from cynthia.daemons.cv import canonical_game_title


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
    ],
)
def test_canonical_game_title_normalizes_ocr_punctuation_and_accents(ocr_text, title):
    assert canonical_game_title(ocr_text) == title


def test_canonical_game_title_corrects_ocr_typo():
    assert canonical_game_title("Pokémon Scerlet") == "Pokémon Scarlet"


def test_canonical_game_title_preserves_unknown_text():
    assert canonical_game_title("Unknown Game") == "Unknown Game"


def test_scrape_text_falls_back_to_paddleocr_2x(monkeypatch):
    import numpy

    from cynthia.daemons import cv

    class Legacy:
        def ocr(self, image, cls=True):
            return [[[None, ("Pokemon Sword", 0.9)]]]

    monkeypatch.setattr(cv, "ocr", Legacy())
    frame = numpy.zeros((10, 10, 3), dtype=numpy.uint8)
    assert cv.CV.scrape_text(frame, w=10, h=10) == "Pokemon Sword"
