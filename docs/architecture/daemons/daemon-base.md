# Daemon process base

**Source:** `cynthia/daemons/daemon.py` — base class `Daemon`.

`Daemon` wraps a worker loop in a `multiprocessing.Process`, creates a
process-local manager namespace, forwards selected shared rings/arguments, and
restores any state snapshot supplied by `DMan`. The child ignores SIGINT
because Ctrl-C reaches the process group; the parent uses `ns.run = False` as
the shutdown signal. Worker exceptions are written through Python logging and
exit with code 1 so the manager can detect the failure.

Subclasses provide a `loop` callable and call `start()` after initializing
their namespace and shared state. `PERSISTED_STATE` lists namespace fields
that survive a manager-driven restart. If a worker needs resources beyond its
child loop, provide a `close()` method to release them after the child exits.
Do not set a daemon's completion marker before its resources are safe to reap.

The base class does not own general retry policy. `DMan` controls discovery,
monitoring, restarts, and final shared-memory cleanup; see the
[manager page](manager.md). Adding unmanaged multiprocessing here can bypass
that lifecycle and make bot shutdown hang or leak state.
