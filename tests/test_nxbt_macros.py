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
