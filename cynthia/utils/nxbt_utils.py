import nxbt
import asyncio
import pickle
from pathlib import Path

from cynthia.utils.strings import shift, unshift

PICKLE_PATH = Path("macros.pkl")

CHAR_MAP = {
    "a": nxbt.Buttons.A,
    "b": nxbt.Buttons.B,
    "x": nxbt.Buttons.X,
    "y": nxbt.Buttons.Y,
    "l": nxbt.Buttons.L,
    "r": nxbt.Buttons.R,
    "zl": nxbt.Buttons.ZL,
    "zr": nxbt.Buttons.ZR,
    "ls": nxbt.Buttons.L_STICK_PRESS,
    "rs": nxbt.Buttons.R_STICK_PRESS,
    "6": nxbt.Buttons.DPAD_UP,
    "v": nxbt.Buttons.DPAD_DOWN,
    ",": nxbt.Buttons.DPAD_LEFT,
    ".": nxbt.Buttons.DPAD_RIGHT,
    "=": nxbt.Buttons.PLUS,
    "-": nxbt.Buttons.MINUS,
    "h": nxbt.Buttons.HOME,
    "c": nxbt.Buttons.CAPTURE,
    "lsl": nxbt.Buttons.JCL_SL,
    "lsr": nxbt.Buttons.JCL_SR,
    "rsl": nxbt.Buttons.JCR_SL,
    "rsr": nxbt.Buttons.JCR_SR,
}


class Input:
    def __init__(
        self, input_list=None, down_duration=0.15, up_duration=0.15, block=True
    ):
        if input_list is None:
            self.input_list = None
        elif not isinstance(input_list, list):
            input_list = [input_list]
        self.input_list = input_list
        self.down_duration = down_duration
        self.up_duration = up_duration
        self.block = block

    async def play(self, nx, controller):
        if self.input_list is None:
            await asyncio.sleep(self.down_duration + self.up_duration)
            return
        try:
            await asyncio.wait_for(
                asyncio.to_thread(
                    nx.press_buttons,
                    controller,
                    self.input_list,
                    down=self.down_duration,
                    up=self.up_duration,
                    block=self.block,
                ),
                timeout=self.down_duration + self.up_duration + 1,
            )
        except TimeoutError:
            pass


tap_home = Input(nxbt.Buttons.HOME, down_duration=0.1, up_duration=0.05)

MACROS = {}


class Macro:

    def __init__(self, inputs=None, *_, name: str = None, force=False):
        self.name = name
        self.original_str = None
        if inputs is not None:
            self.parse_inputs(inputs, force)

    def parse_inputs(self, inputs, force=False):
        self.clear()

        if isinstance(inputs, str):
            self.original_str = inputs
            if inputs.startswith("$"):
                lines = inputs.split("\n")
                if len(lines) > 1:
                    macro_name = (
                        lines[0].strip().replace(" ", "_").replace("$", "").lower()
                    )
                    if macro_name.startswith("!"):
                        force = True
                        macro_name = macro_name.replace("!", "")
                    inputs = "\n".join(lines[1:])
                    if self.name is None:
                        self.name = macro_name

            content = unshift(inputs.strip(), exclude="$").split("\n")
            for line in content:

                def detect_and_remove(line: str, match: str):
                    if match in line:
                        modified = line.replace(match, "")
                        return modified, True
                    return line, False

                down_duration = 0.15
                up_duration = 0.15

                line, matched = detect_and_remove(line, "hold")
                if matched:
                    down_duration = 1.0
                line, matched = detect_and_remove(line, "tap")
                if matched:
                    down_duration = 0.05
                    up_duration = 0.02

                for macro, _input in sorted(MACROS.items(), key=lambda x: -len(x[0])):
                    line, matched = detect_and_remove(line, macro)
                    if matched:
                        self.input_list.append(_input)

                _inputs = []
                for char in sorted(CHAR_MAP.keys(), key=lambda x: -len(x)):
                    if char in line:
                        line = line.replace(char, "")
                        _inputs.append(CHAR_MAP[char])
                self.input_list.append(
                    Input(_inputs, down_duration=down_duration, up_duration=up_duration)
                )
        else:
            self.input_list = [
                _input if isinstance(_input, Input) else Input(_input)
                for _input in inputs
            ]

        if self.name:
            if force or self.name.lower() not in MACROS.keys():
                MACROS[self.name.lower()] = self

    def redefine(self):
        if self.original_str is not None:
            self.parse_inputs(self.original_str, force=True)

    def get(self):
        if getattr(self, "original_str", None) is not None:
            return self.original_str

    def clear(self):
        self.input_list = list()

    async def play(self, nx, controller):
        if nx is None or controller is None:
            return
        if nx.state[controller]["state"] != "connected":
            return
        for _input in self.input_list:
            await _input.play(nx, controller)


MACROS["wait"] = Input(None, down_duration=1, up_duration=0)
zoom = Macro("tap home\ntap home", name="zoom")
cleanup = Macro(
    [
        Input(nxbt.Buttons.HOME, up_duration=1.0),
        nxbt.Buttons.DPAD_DOWN,
        nxbt.Buttons.DPAD_RIGHT,
        nxbt.Buttons.DPAD_RIGHT,
        nxbt.Buttons.DPAD_RIGHT,
        nxbt.Buttons.DPAD_RIGHT,
        nxbt.Buttons.DPAD_RIGHT,
        nxbt.Buttons.DPAD_RIGHT,
        Input(nxbt.Buttons.A, up_duration=1.5),
        Input(nxbt.Buttons.A, up_duration=0, block=False),
    ],
    name="cleanup",
)


def load_macros(drive_path):
    pickle_path = drive_path / PICKLE_PATH
    if pickle_path.exists() and pickle_path.is_file():
        with open(pickle_path, "rb") as f:
            _macros = pickle.load(f)
            for key, value in _macros.items():
                if key not in MACROS.keys():
                    MACROS[key] = value


def save_macros(drive_path):
    if drive_path.exists() and drive_path.is_dir():
        pickle_path = drive_path / PICKLE_PATH
        with open(pickle_path, "wb") as f:
            pickle.dump(MACROS, f)
