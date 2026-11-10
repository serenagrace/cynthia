# CyNX network daemon

**Source:** `cynthia/daemons/cynx.py` — `CyNXDaemon` and its `run_client`
worker; protocol client in `cynthia/utils/cynx.py`.

## Responsibility

`CyNXDaemon` is the sole owner of the bot-side CyNX command and macro sockets.
It discovers the Pi on active IPv4 broadcast addresses, validates the offer,
authenticates both channels, sends status heartbeats, and translates queued
controller IPC requests into protocol calls. `NXBTDaemon` uses
`CyNXController` as an adapter, so macro parsing and playback position remain
in the existing controller worker.

## IPC and delivery invariants

`DMan` supplies an input queue, a manager-backed reply map, and a bounded error
alert queue. The client process services no more than 32 queued IPC records per
loop turn and owns all network sockets. A controller step uses the second,
sequential macro channel: one step is in flight, it must receive a matching
session and step ID, and `accepted` must precede `completed`. The server's
completion ledger lets the client resume the same session without replaying a
confirmed step. When an uncompleted step is interrupted, the controller worker
may retry that step after transport fallback; a partial physical game action
can therefore repeat.

The daemon publishes network availability, Switch/USB connection state,
reconnect state, errors, and the time when safe Bluetooth fallback is allowed.
Each transition into a connected USB state also advances a shared connection
counter, so the controller worker can perform CV-gated menu setup once for
startup, explicit connects, and later reconnections.
When the network session is lost, it honors the protocol heartbeat timeout,
reconnect grace, and bounded recovery window rather than immediately opening a
second controller. An explicit `/cynx disconnect` runs the Pi's cleanup and
leaves USB idle without releasing the authenticated network session, owner, or
channels; later connect/status requests continue on those channels.
Grace-expired loss and explicit disconnect use the same cleanup input sequence.

Queue cancellation sends `stop`. During shutdown, `DMan` stops macro playback
and lets `NXBTDaemon` disconnect while `CyNXDaemon` is still running. The
transport then cancels outstanding jobs, sends `release` when the session is
healthy, waits for its acknowledgment, and closes both channels. Release
cleans up any still-bound USB controller and relinquishes the Pi lease without
starting connection-loss recovery. Unexpected channel loss still uses the
normal reconnect grace and recovery path.

For intentional `disconnect` and `release`, a fresh, confident
`change_grip_order` match adds `skip_cleanup: true` to the owner command. This
skips only menu-navigation inputs; the Pi still cancels active work,
neutralizes input, and unbinds USB. Uncertain or stale CV omits the flag, and
unexpected network-loss recovery is unchanged.

## Configuration and extension

`cynx_enabled`, `cynx_auto_connect`, command/macro ports, heartbeat/discovery timing, and
`CYNX_PASSPHRASE` are supplied to this daemon from `Context`. Discovery is LAN
broadcast, not a configured static host. Do not log the shared passphrase; the
error relay redacts it and remembers up to 256 error IDs per worker run. New
error events continue to enter local logs; owner alerts throttle identical
messages for 60 seconds, and the manager-backed alert queue is bounded to 100
items.

`cynx_auto_connect` controls initial USB intent, not network discovery.
Manual connect/disconnect updates that intent; explicitly connected controllers
can still recover from a later network interruption.

Keep `CyNXClient` as the network protocol owner and use the IPC `request()`
bridge for consumers outside this process. Do not open a second set of sockets
from commands or cogs. Tests for step acknowledgment order, cancellation,
reconnect, fallback and shutdown are in `tests/test_cynx.py`.
