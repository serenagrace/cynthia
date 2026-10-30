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
