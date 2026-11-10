# Controller and macro daemon

**Source:** `cynthia/daemons/nxbt.py` — `NXBTDaemon`; macro parser and
Bluetooth setup are in `cynthia/utils/nxbt_utils.py`.

## Responsibility

`NXBTDaemon` is the single controller/playback worker. It owns controller
connection state, parses queued macro strings into input steps, executes
through Bluetooth NXBT or a `CyPiController`, and tracks loop, pause, stop,
watchdog, encounter-reset, and hunt-log state. It runs above capture/stream
workers in process priority because input timing is latency-sensitive.

## Queue and transport invariants

Each queue entry is `(epoch, serialized_macro)`. `stop()` increments the epoch,
sets stop/pause, and sends a best-effort CyPi stop; entries from older epochs
are discarded instead of starting after a stop. `pause()` only stops future
macro progress and preserves the queue. This is separate from controller
disconnect. The current input generator is retained across asynchronous
playback, and `unpause()` clears pending stop signals.

Automatic connection prefers a discovered CyPi when available. Explicit
`nxbt` and `cypi` backends select one transport, and changing transports stops
playback first. Bluetooth connection uses the setup sequence in
`nxbt_utils.nxbt_connect`; Bluetooth disconnect uses its `cleanup` macro.
For CyPi, this worker sends commands through the CyPi daemon and delays
Bluetooth fallback until the Pi has completed its recovery/detach window.
For each new wired connection, `cypi_connect_setup` waits for fresh CV data and
plays `A`, wait, `A`, wait, `B`, wait, `HOME` only on a confident
`change_grip_order` match. Setup completes before playback resumes and does
not block the separate transport's heartbeats. Missing or stale CV skips the
setup inputs. `cypi_auto_connect: false` disables unsolicited startup connection,
without disabling manual connect or discovery.
Both wired and Bluetooth disconnect also check fresh CV before menu cleanup:
when Change Grip/Order is already open, navigation is skipped but the
controller is still detached.

CyPi steps have accepted/completed acknowledgments. After a lost connection,
the worker reconnects to the same playback session, advances past a confirmed
step, and retries only the last uncompleted step after Bluetooth takeover. A
retried incomplete step may repeat partial game effects; the protocol does not
provide exactly-once gameplay. Active Bluetooth hunts are not automatically
switched to CyPi.

The looping watchdog derives a timeout from encounter intervals, with a
10-minute minimum and at least twice the measured average. Encounter-reset
logic can restart a loop five seconds after an encounter. Possible shiny
detection pauses the macro and exposes an alert signal for `StatusCog`.

## Safe changes and tests

Preserve epoch invalidation, one active controller owner, step acknowledgment
ordering, and playback resumption. Do not add a second macro queue in a command
or cog. Controller and macro regression tests are in
`tests/test_nxbt_macros.py`, `tests/test_cypi.py`, and
`tests/test_simulated_commands.py`.
