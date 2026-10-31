"""Base process wrapper used by bot daemons."""

import time
from multiprocessing import Manager, Process


class Daemon:
    """Run a daemon loop in a child process with shared state."""

    # Namespace attributes carried over when the manager restarts the daemon
    PERSISTED_STATE = ()

    def __init__(self, dman, *args, fbs=None, tqueue=False):
        """Create shared namespace state and resolve shared-frame references."""
        self.process = None
        self._manager = Manager()
        self.ns = self._manager.Namespace()
        self.ns.run = True
        self.uns = dman.uns
        self._pending_state = getattr(dman, "pending_state", {}).pop(
            type(self).__name__, {}
        )
        self.fbs = tuple()
        if fbs is not None:
            for idx in fbs:
                self.fbs += (dman.fb[idx * 2].name,)
                self.fbs += (dman.fb[1 + idx * 2].name,)
        self._args = args

    def start(self, *, daemon=True):
        """Start the daemon loop in a child process."""
        self.restore_state(self._pending_state)
        self.process = Process(
            target=self.loop, args=(self.ns, self.uns) + self.fbs + self._args
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
