from cynthia.utils.namespace import Namespace

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

ANSI_COLORS = Namespace(
    {
        "BLACK": "\033[30m",
        "RED": "\033[31m",
        "GREEN": "\033[32m",
        "YELLOW": "\033[33m",
        "BLUE": "\033[34m",
        "MAGENTA": "\033[35m",
        "CYAN": "\033[36m",
        "WHITE": "\033[37m",
    }
)


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


def color_str(string: str, color_code: str):
    if color_code.upper() not in ANSI_COLORS.keys():
        return string
    return f"{ANSI_COLORS[color_code.upper()]}{string}\033[0m"
