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


def test_sample_macro_dependencies_resolve_without_the_live_drive():
    """Every conditional branch and nested macro must ship or be built in."""
    from pathlib import Path

    from cynthia.utils.nxbt_utils import Ternary

    original_tree = Macro._macro_tree
    Macro.bind_macro_tree({})
    try:
        paths = sorted((Path(__file__).parents[1] / "examples/macros").glob("*.txt"))
        # Register every definition before parsing so file order cannot hide a dependency.
        for path in paths:
            header, body = path.read_text().split("\n", 1)
            assert header == f"${path.stem}"
            Macro._macro_tree[path.stem] = body
        for path in paths:
            macro = Macro(path.read_text())
            for step in macro.walk():
                if isinstance(step, Ternary):
                    for dependency in (step.true_macro, step.false_macro):
                        assert dependency in Macro._macro_tree, (path, dependency)
                        assert list(Macro.get(dependency).walk()), (path, dependency)
    finally:
        Macro._macro_tree = original_tree


def test_nxbt_worker_preserves_connection_queue_and_cleanup(monkeypatch, tmp_path):
    """Play one queued input with the real worker, but no Bluetooth or subprocesses."""
    from queue import Queue
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from cynthia.daemons import nxbt as worker
    from cynthia.utils.drive import Drive

    def initialize(self, dman, *args, **kwargs):
        """Create local namespaces in place of multiprocessing managers."""
        self.ns = SimpleNamespace(run=True)
        self.uns = dman.uns

    calls = []

    class Controller:
        """Record controller activity and request shutdown after the first input."""

        state = {0: {"state": "connected"}}

        def press_buttons(self, *args, **kwargs):
            """Record a press and finish this bounded worker run."""
            calls.append("input")
            daemon.ns.run = False

        def _on_exit(self):
            """Record cleanup of NXBT's internal processes."""
            calls.append("cleanup")

    async def connect(nx):
        """Report a connected controller and allow playback."""
        calls.append("connect")
        daemon.ns.pause = False
        return True, 0

    monkeypatch.setattr(worker.Daemon, "__init__", initialize)
    monkeypatch.setattr(worker.NXBTDaemon, "start", lambda self, **k: None)
    monkeypatch.setattr(worker.multiprocessing, "Queue", Queue)
    monkeypatch.setattr(worker.nxbt, "Nxbt", Controller)
    monkeypatch.setattr(worker.os, "setpriority", lambda *a: None)
    monkeypatch.setattr(worker, "nxbt_connect", connect)
    disconnect = AsyncMock(return_value=True)
    monkeypatch.setattr(worker, "nxbt_disconnect", disconnect)
    dman = SimpleNamespace(
        uns=SimpleNamespace(),
        manager=SimpleNamespace(dict=dict),
        drive=Drive(tmp_path),
        context=SimpleNamespace(config={}),
    )
    original_tree = Macro._macro_tree
    try:
        daemon = worker.NXBTDaemon(dman)
        daemon.ns.connect = True
        # An input queued before clear must be discarded before the current epoch runs.
        daemon.tqueue.put((-1, "B"))
        daemon.queue("(0,0) A")
        daemon.loop(daemon.ns, daemon.uns, daemon.tqueue, Macro._macro_tree, dman.drive)
        assert calls == ["connect", "input", "cleanup"]
        assert daemon.ns.done
        disconnect.assert_awaited_once()
        assert dman.drive.exists("macros.json", is_file=True)
    finally:
        Macro._macro_tree = original_tree


def test_home_tap_closes_quick_settings_and_retries(monkeypatch):
    import asyncio

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
