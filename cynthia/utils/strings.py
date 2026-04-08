SHIFT_PAIRS = [
    ("!", "1"),
    ("@", "2"),
    ("#", "3"),
    ("$", "4"),
    ("%", "5"),
    ("^", "6"),
    ("&", "7"),
    ("*", "8"),
    ("(", "9"),
    (")", "0"),
    ("_", "-"),
    ("+", "="),
    ("~", "`"),
    ("{", "["),
    ("}", "]"),
    ("|", "\\"),
    (":", ";"),
    ('"', "'"),
    ("<", ","),
    (">", "."),
    ("?", "/"),
]


def unshift(string: str, exclude=None):
    string = string.lower()
    for shifted, unshifted in SHIFT_PAIRS:
        if exclude is not None:
            if isinstance(exclude, str):
                if exclude == shifted:
                    continue
            if hasattr(exclude, "__iter__"):
                if shifted in exclude:
                    continue
        string = string.replace(shifted, unshifted)
    return string


def shift(string: str):
    string = string.upper()
    for shifted, unshifted in SHIFT_PAIRS:
        string = string.replace(unshifted, shifted)
    return string
