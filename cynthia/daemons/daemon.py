"""Base process wrapper used by bot daemons."""

import logging
import signal
import time
from multiprocessing import Manager, Process


def _run_loop(loop, args):
    """Run a daemon loop with Ctrl-C ignored; the parent stops it via ``ns.run``.

    Ctrl-C reaches the whole process group. Without this, children die with a
    KeyboardInterrupt and the monitor treats that as a crash and restarts them.
    """
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        loop(*args)
    except Exception:
        # multiprocessing would print this to stderr only; log it for the file.
        # Exit code 1 matches an uncaught exception, so the monitor restarts it
        logging.getLogger(__name__).exception(
            f"`{getattr(loop, '__qualname__', loop)}` crashed"
        )
        raise SystemExit(1)


class Daemon:
    """Run a daemon loop in a child process with shared state."""

    # Namespace attributes carried over when the manager restarts the daemon
    PERSISTED_STATE = ()

    def __init__(
        self, dman, *args, ring=False, audio_ring=False, native_ring=False, tqueue=False
    ):
        """Create shared namespace state and resolve shared-frame references."""
        self.process = None
        self._manager = Manager()
        self.ns = self._manager.Namespace()
        self.ns.run = True
        self.uns = dman.uns
        self._pending_state = getattr(dman, "pending_state", {}).pop(
            type(self).__name__, {}
        )
        # The shared frame ring is inherited by the child process, not pickled
        self.ring = (dman.ring,) if ring else tuple()
        if audio_ring:
            self.ring += (dman.audio_ring,)
        if native_ring:
            self.ring += (dman.native_ring,)
        self._args = args

    def start(self, *, daemon=True):
        """Start the daemon loop in a child process."""
        self.restore_state(self._pending_state)
        self.process = Process(
            target=_run_loop,
            args=(self.loop, (self.ns, self.uns) + self.ring + self._args),
        )
        self.process.daemon = daemon
        self.process.start()
        self.started_at = time.time()

    def snapshot_state(self):
        """Return the persisted namespace attributes of a running daemon."""
        return {
            key: getattr(self.ns, key)
            for key in self.PERSISTED_STATE
            if hasattr(self.ns, key)
        }

    def restore_state(self, state):
        """Apply a snapshot taken from a previous instance of this daemon."""
        for key, value in state.items():
            setattr(self.ns, key, value)

    def close(self):
        """Shut down the manager process backing this daemon's namespace."""
        self._manager.shutdown()
