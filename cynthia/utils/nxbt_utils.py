import nxbt
import asyncio

from cynthia.utils.strings import shift, unshift

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
    def __init__(self, input_list=None, down_duration=0.15, up_duration=0.15):
        if input_list is None:
            self.input_list = None
        elif not isinstance(input_list, list):
            input_list = [input_list]
        self.input_list = input_list
        self.down_duration = down_duration
        self.up_duration = up_duration

    async def play(self, nx, controller):
        if self.input_list is None:
            await asyncio.sleep(self.down_duration + self.up_duration)
            return
        await asyncio.to_thread(
            nx.press_buttons,
            controller,
            self.input_list,
            down=self.down_duration,
            up=self.up_duration,
        )


tap_home = Input(nxbt.Buttons.HOME, down_duration=0.1, up_duration=0.05)

MACROS = {}


class Macro:

    def __init__(self, name: str = None, inputs=None):
        self.name = name
        if inputs is not None:
            self.parse_inputs(inputs)

    def parse_inputs(self, inputs):
        self.clear()

        if isinstance(inputs, str):
            if inputs.startswith("$"):
                lines = inputs.split("\n")
                if len(lines) > 1:
                    macro_name = (
                        lines[0].strip().replace(" ", "_").replace("$", "").lower()
                    )
                    content = "\n".join(lines[1:])
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
                    down_duration = 0.10
                    up_duration = 0.10

                for macro, _input in MACROS.items():
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
            if self.name.lower() not in MACROS.keys():
                MACROS[self.name.lower()] = self

    def clear(self):
        self.input_list = list()

    async def play(self, nx, controller):
        if nx is None or controller is None:
            return
        for _input in self.input_list:
            await _input.play(nx, controller)


MACROS["wait"] = (Input(None, down_duration=1, up_duration=0),)
zoom = Macro("zoom", "tap home\ntap home")
cleanup = Macro(
    "cleanup",
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
        nxbt.Buttons.A,
    ],
)
