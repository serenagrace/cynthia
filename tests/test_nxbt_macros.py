import nxbt

from cynthia.utils.nxbt_utils import DURATIONS, Input, Macro


def test_macro_parser_maps_buttons_and_durations_without_controller():
    original_tree = Macro._macro_tree
    Macro.bind_macro_tree({})
    try:
        macro = Macro("A\nwait\nB")

        inputs = list(macro.walk())
        assert len(inputs) == 3
        assert all(isinstance(item, Input) for item in inputs)
        assert inputs[0].input_list == [nxbt.Buttons.A]
        assert inputs[1].input_list == []
        assert (inputs[1].down_duration, inputs[1].up_duration) == DURATIONS["wait"]
        assert inputs[2].input_list == [nxbt.Buttons.B]
    finally:
        Macro._macro_tree = original_tree


def test_home_tap_closes_quick_settings_and_retries(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    import nxbt

    from cynthia.utils import nxbt_utils

    monkeypatch.setattr(nxbt_utils, "QUICK_SETTINGS_WINDOW", 0.05)
    monkeypatch.setattr(nxbt_utils, "QUICK_SETTINGS_POLL", 0.01)
    presses = []
    menu_opens = [True, False]
    menu = {"open": False}

    class FakeUns:
        quick_settings_watch = False

        @property
        def quick_settings_open(self):
            # CVDaemon only reports while watching
            return self.quick_settings_watch and menu["open"]

        @quick_settings_open.setter
        def quick_settings_open(self, value):
            pass

    uns = FakeUns()

    class FakeNx:
        def press_buttons(self, controller, buttons, down, up, block):
            presses.append(buttons[0])
            if buttons[0] == nxbt.Buttons.HOME:
                menu["open"] = menu_opens.pop(0)
            elif buttons[0] == nxbt.Buttons.B:
                menu["open"] = False

    asyncio.run(nxbt_utils.tap_home.play(FakeNx(), 0, uns=uns))

    assert presses == [nxbt.Buttons.HOME, nxbt.Buttons.B, nxbt.Buttons.HOME]
    assert uns.quick_settings_recovered == 1
    assert not uns.quick_settings_watch


def test_home_tap_without_menu_presses_once(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from cynthia.utils import nxbt_utils

    monkeypatch.setattr(nxbt_utils, "QUICK_SETTINGS_WINDOW", 0.05)
    monkeypatch.setattr(nxbt_utils, "QUICK_SETTINGS_POLL", 0.01)
    presses = []
    uns = SimpleNamespace(quick_settings_watch=False, quick_settings_open=False)

    class FakeNx:
        def press_buttons(self, *args, **kwargs):
            presses.append(args[1])

    asyncio.run(nxbt_utils.tap_home.play(FakeNx(), 0, uns=uns))
    assert len(presses) == 1
