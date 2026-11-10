# Daemon manager

**Source:** `cynthia/daemons/dman.py` — `DMan`, `FreezeWatch`, and `FB0`.

## Discovery and lifecycle

`DMan` creates `Drive`, BGR/native video rings, an audio ring, manager-backed
shared state and CyPi IPC queues before importing daemon modules. It scans
direct files in `cynthia/daemons/`, excluding `__init__`, `dman`, `daemon`,
and `frames`; each imported module contributes its public `Daemon` subclasses.
All discovered classes are instantiated during bot construction.

`stop_daemons()` clears each `ns.run`, waits up to 30 seconds for workers to
finish, reaps them, closes per-daemon managers, then unlinks frame/audio rings
and shuts down the global manager. A worker should cooperate with this protocol
instead of relying on forced termination.

## Monitoring and restart boundaries

The monitor reaps unexpected process exits and checks capture/CV production
for stalls. Only `UVCDaemon` and `CVDaemon` are manager-restartable; only
`CYStream` and `UVCDaemon` are supported for module reload. A restart snapshots
the daemon's declared persisted state, stops the old process, and creates a
fresh instance. Extend these allowlists only when state/resource behavior has
been verified.

`FreezeWatch` distinguishes a moving clock with a frozen frame hash from a
capture stall. It does not treat the no-signal screen or stale frame data as a
freeze. After `capture_freeze_seconds`, the manager restarts the capture
daemon, backs off after repeated failures, and notifies the owner on recovery
escalation.

Tests for discovery, reload, restart, and freeze behavior are in
`tests/test_dman.py` and `tests/test_reload.py`.
