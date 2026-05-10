import nxbt
import logging
import re
import asyncio
import json

from cynthia.utils.strings import shift, unshift

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

JSON_PATH = "macros.json"

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
CHAR_UNMAP = {value: key for key, value in CHAR_MAP.items()}

DURATIONS = {
    "default": (0.15, 0.15),
    "hold": (1.0, 0.15),
    "tap": (0.05, 0),
    "wait": (1.0, 1.0),
}


class Input:
    def __init__(
        self,
        input_list=None,
        down_duration=DURATIONS["default"][0],
        up_duration=DURATIONS["default"][1],
        block=True,
    ):
        if input_list is None:
            self.input_list = list()
        elif not isinstance(input_list, list):
            input_list = [input_list]
        self.input_list = input_list
        self.down_duration = down_duration
        self.up_duration = up_duration
        self.block = block

    async def play(self, nx, controller):
        if not self.input_list:
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

    def __str__(self):
        input_str, duration_str = self.input_str(), self.duration_str()
        if input_str is None:
            return duration_str
        if duration_str is None:
            return input_str
        return duration_str + " " + input_str

    def input_str(self):
        if self.input_list is None:
            return None
        return shift(
            " ".join(CHAR_UNMAP[_input] for _input in self.input_list),
            exclude=["-", "v"],
        )

    def duration_str(self):
        duration_str = f"({self.down_duration},{self.up_duration})"
        for key, durations in DURATIONS.items():
            if (self.down_duration, self.up_duration) == durations:
                if key == "default":
                    return None
                duration_str = key
        return duration_str


tap_home = Input(nxbt.Buttons.HOME, down_duration=0.1, up_duration=0.05)


class Macro:
    MACROS = {}

    def __init__(self, inputs=None, *_, name: str = None, force=False):
        self.name = name
        if inputs is not None:
            self.parse_inputs(inputs, force)

    def parse_inputs(self, inputs, force=False):
        self.clear()
        if isinstance(inputs, str):
            force = self.from_str(inputs) or force
        else:
            if not hasattr(inputs, '__iter__'):
                inputs = [ inputs ]
            self.input_list = [
                _input if isinstance(_input, Input) else Input(_input)
                for _input in inputs
            ]

        if self.name:
            if force or self.name.lower() not in Macro.MACROS.keys():
                Macro.MACROS[self.name.lower()] = self

        logger.debug(str(self))

    def from_str(self, inputs: str):
        force = False
        self.original_str = inputs
        if inputs.startswith("$"):
            lines = inputs.split("\n")
            if len(lines) > 1:
                macro_name = lines[0].strip().replace(" ", "_").replace("$", "").lower()
                if macro_name.startswith("!"):
                    force = True
                    macro_name = macro_name.replace("!", "")
                inputs = "\n".join(lines[1:])
                if self.name is None:
                    self.name = macro_name

        content = unshift(inputs.strip(), exclude="$").split("\n")
        for line in content:

            def detect_and_remove(line: str, match: str):
                if unshift(match) in unshift(line):
                    modified = line.replace(unshift(match), "")
                    return modified, True
                return line, False

            down_duration, up_duration = None, None

            result = re.search(r"\(([0-9]*(?:.[0-9]+)?),([0-9]*(?:.[0-9]+)?)\)", line)
            if result:
                down_duration, up_duration = result.groups()
                line = re.sub(
                    r"\(([0-9]*(?:.[0-9]+)?),([0-9]*(?:.[0-9]+)?)\)", "", line
                )
                if down_duration.isspace() or not down_duration:
                    down_duration = None
                if up_duration.isspace() or not up_duration:
                    up_duration = None

            for key, value in DURATIONS.items():
                if key == "default":
                    continue
                line, matched = detect_and_remove(line, key)
                if matched:
                    down_duration, up_duration = value

            down_duration = (
                down_duration if down_duration is not None else DURATIONS["default"][0]
            )
            up_duration = (
                up_duration if up_duration is not None else DURATIONS["default"][1]
            )

            for macro, _input in sorted(Macro.MACROS.items(), key=lambda x: -len(x[0])):
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
        return force

    def redefine(self):
        if self.original_str is not None:
            self.parse_inputs(self.original_str, force=True)

    def clear(self):
        self.input_list = list()

    async def play(self, nx, controller):
        if nx is None or controller is None:
            return
        if nx.state[controller]["state"] != "connected":
            return
        for _input in self.input_list:
            await _input.play(nx, controller)

    def walk(self):
        for _input in self.input_list:
            yield _input

    def __str__(self):
        return "\n".join(str(_input) for _input in self.input_list)


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


def load_macros(drive):
    if drive.enabled and drive.exists(JSON_PATH, is_file=True):
        with drive.open(JSON_PATH, "rb") as f:
            _macros = json.load(f)
            for key, value in _macros.items():
                if key not in Macro.MACROS.keys():
                    Macro.MACROS[key] = Macro(value)


def save_macros(drive):
    if drive.enabled:
        with drive.open(JSON_PATH, "w") as f:
            dump = {key: str(val) for key, val in Macro.MACROS.items()}
            json.dump(dump, f)


async def nxbt_connect(nx, timeout=30):
    controller = nx.create_controller(nxbt.PRO_CONTROLLER, colour_body=[215, 0, 255])

    try:
        await asyncio.wait_for(
            asyncio.to_thread(nx.wait_for_connection, controller), timeout=30
        )
    except TimeoutError:
        nx.remove_controller(controller)
        return False, None

    await asyncio.sleep(2)

    await Macro(
        [Input(nxbt.Buttons.A, up_duration=1.0), nxbt.Buttons.B, nxbt.Buttons.HOME]
    ).play(nx, controller)

    return True, controller


async def nxbt_disconnect(nx, controller):
    if controller is not None:
        try:
            await asyncio.wait_for(
                Macro.MACROS["cleanup"].play(nx, controller), timeout=15
            )
        except TimeoutError:
            pass
        await asyncio.sleep(1)
        try:
            await asyncio.wait_for(
                asyncio.to_thread(nx.remove_controller, controller), timeout=10
            )
        except TimeoutError:
            return False
    return True
