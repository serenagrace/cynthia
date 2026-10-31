import multiprocessing
from multiprocessing.connection import wait
from types import SimpleNamespace
from unittest.mock import Mock

from cynthia.daemons.dman import DMan


def _exit_worker():
    pass


def test_reap_exited_daemon_process():
    dman = DMan.__new__(DMan)
    process = Mock()
    process.is_alive.return_value = False
    process.exitcode = 1
    daemon = SimpleNamespace(process=process, ns=SimpleNamespace(run=True))
    dman._DMan__running_daemons = {"worker": daemon}

    dman.reap_exited_daemons()

    process.join.assert_called_once_with()
    assert daemon.ns.run is False


def test_reap_exited_real_process():
    dman = DMan.__new__(DMan)
    process = multiprocessing.Process(target=_exit_worker)
    process.start()
    daemon = SimpleNamespace(process=process, ns=SimpleNamespace(run=True))
    dman._DMan__running_daemons = {"worker": daemon}

    try:
        assert wait([process.sentinel], timeout=5)
        dman.reap_exited_daemons()
        assert process.exitcode == 0
        assert daemon.ns.run is False
    finally:
        process.join()


def test_stalled_daemons_detects_stale_frames_and_heartbeat():
    dman = DMan.__new__(DMan)
    alive = Mock()
    alive.is_alive.return_value = True
    now = 1000.0
    dman.uns = SimpleNamespace(uvc_time0=int(900e9), uvc_time1=None)
    dman._DMan__running_daemons = {
        "UVCDaemon": SimpleNamespace(
            process=alive, ns=SimpleNamespace(run=True), started_at=0.0
        ),
        "CVDaemon": SimpleNamespace(
            process=alive, ns=SimpleNamespace(run=True, heartbeat=now), started_at=0.0
        ),
    }
    assert dman.stalled_daemons(now) == ["UVCDaemon"]

    dman.uns.uvc_time1 = int(999e9)
    dman._DMan__running_daemons["CVDaemon"].ns.heartbeat = 900.0
    assert dman.stalled_daemons(now) == ["CVDaemon"]


def test_restart_daemon_carries_state_and_closes_manager():
    import asyncio

    dman = DMan.__new__(DMan)
    dman.pending_state = {}
    process = Mock()
    process.is_alive.side_effect = [True, False, False]
    daemon = Mock(process=process, ns=SimpleNamespace(run=True))
    daemon.snapshot_state.return_value = {"self_encounter": True}
    dman._DMan__running_daemons = {"CVDaemon": daemon}
    dman.run_daemons = Mock()

    assert asyncio.run(dman.restart_daemon("CVDaemon"))

    process.terminate.assert_called_once()
    daemon.close.assert_called_once()
    assert dman.pending_state == {"CVDaemon": {"self_encounter": True}}
    dman.run_daemons.assert_called_once_with(daemons=["CVDaemon"])
    assert "CVDaemon" not in dman._DMan__running_daemons
