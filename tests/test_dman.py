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
    dman.ring = SimpleNamespace(last_time_ns=int(900e9))
    dman._DMan__running_daemons = {
        "UVCDaemon": SimpleNamespace(
            process=alive, ns=SimpleNamespace(run=True), started_at=0.0
        ),
        "CVDaemon": SimpleNamespace(
            process=alive, ns=SimpleNamespace(run=True, heartbeat=now), started_at=0.0
        ),
    }
    assert dman.stalled_daemons(now) == ["UVCDaemon"]

    dman.ring.last_time_ns = int(999e9)
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


def _freeze_dman(frame_hash=7, scores=None):
    """A manager with a live capture daemon whose ring publishes `frame_hash`."""
    import time
    from unittest.mock import AsyncMock

    from cynthia.daemons.dman import FreezeWatch

    dman = DMan.__new__(DMan)
    alive = Mock()
    alive.is_alive.return_value = True
    dman._DMan__running_daemons = {
        "UVCDaemon": SimpleNamespace(process=alive, ns=SimpleNamespace(run=True))
    }
    dman.ring = SimpleNamespace(last_hash=frame_hash, last_time_ns=time.time_ns())
    dman.uns = SimpleNamespace(ssim_scores=scores or [("home", 0.5)])
    dman.context = SimpleNamespace(config={"capture_freeze_seconds": 120})
    dman.freeze_watch = FreezeWatch()
    dman._last_restart = {}
    dman.restart_daemon = AsyncMock(return_value=True)
    dman.notify = AsyncMock()
    return dman


def test_frozen_picture_resets_capture_and_notifies_with_backoff():
    import asyncio
    import time

    dman = _freeze_dman()
    now = time.time()

    async def at(offset, frame_hash=None):
        if frame_hash is not None:
            dman.ring.last_hash = frame_hash
        dman.ring.last_time_ns = int((now + offset) * 1e9)
        return await dman.watch_capture_freeze(now + offset)

    async def run():
        assert await at(0) is None
        assert await at(119) is None
        assert await at(121) == "frozen"
        dman.restart_daemon.assert_awaited_once_with("UVCDaemon")
        assert "frozen" in dman.notify.await_args.args[0]
        # A reset card shows a few new pictures before freezing again
        assert await at(125, 8) is None
        assert await at(126, 7) is None
        assert await at(300) is None  # the second wait is doubled
        assert await at(367) == "frozen"
        assert dman.notify.await_count == 1
        assert await at(367 + 481) == "frozen"
        assert "still frozen after 3" in dman.notify.await_args.args[0]
        for i in range(5):
            result = await at(900 + i, 100 + i)
        assert result == "recovered"
        assert "moving again" in dman.notify.await_args.args[0]

    asyncio.run(run())
    assert dman.restart_daemon.await_count == 3


def test_freeze_ignores_no_signal_stale_frames_and_disabled_setting():
    import asyncio
    import time

    now = time.time()
    no_signal = _freeze_dman(scores=[("elgato_no_signal", 0.99)])
    stale = _freeze_dman()
    stale.ring.last_time_ns = int((now - 60) * 1e9)
    disabled = _freeze_dman()
    disabled.context.config["capture_freeze_seconds"] = 0

    async def run():
        for dman in (no_signal, stale, disabled):
            for offset in (0, 200, 1000):
                if dman is not stale:
                    dman.ring.last_time_ns = int((now + offset) * 1e9)
                assert await dman.watch_capture_freeze(now + offset) is None
            dman.restart_daemon.assert_not_awaited()

    asyncio.run(run())


def test_frame_ring_publishes_last_hash():
    from cynthia.daemons.frames import FrameRing

    ring = FrameRing((2, 2, 3))
    try:
        assert ring.last_hash == 0
        slot = ring.begin_write()
        ring.end_write(slot, 1, 0xDEADBEEF)
        assert ring.last_hash == 0xDEADBEEF
    finally:
        ring.close(unlink=True)
