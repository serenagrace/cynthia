"""Daemon that connects to Nintendo Switch and plays queued macros."""

import asyncio
import logging
import multiprocessing
import os
import time
from queue import Empty

import nxbt

from cynthia.utils.cypi import (
    CyPiController,
    CyPiError,
    CyPiStopped,
    CyPiUnavailable,
)
from cynthia.utils.cypi import request as cypi_request
from cynthia.utils.encounters import (
    DEFAULT_ENCOUNTER_LOG,
    START_MARKER,
    STOP_MARKER,
    average_interval_ms,
    marker_line,
)
from cynthia.utils.log import setup_logging
from cynthia.utils.nxbt_utils import (
    Macro,
    cypi_connect_setup,
    load_macros,
    nxbt_connect,
    nxbt_disconnect,
    save_macros,
)

from .daemon import Daemon

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class NXBTDaemon(Daemon):
    """Execute queued macros through CyPi USB or NXBT Bluetooth."""

    POLL_RATE = 0.5
    GRACE_PERIOD = 5.0
    WATCHDOG_DEFAULT_TIMEOUT = 60 * 10
    ENCOUNTER_GRACE = 5.0
    WATCHDOG_AVERAGE_FACTOR = 2
    WATCHDOG_MIN_SAMPLES = 15

    @staticmethod
    def watchdog_timeout(drive, log_name):
        """Return twice the average encounter interval, never below the 10-minute default."""
        try:
            with drive.open(log_name, "r", touch=True) as f:
                average_ms = average_interval_ms(
                    f.readlines(), min_samples=NXBTDaemon.WATCHDOG_MIN_SAMPLES
                )
        except Exception:
            logger.exception("Failed to read encounter log for watchdog")
            average_ms = None
        if not average_ms:
            return NXBTDaemon.WATCHDOG_DEFAULT_TIMEOUT
        return max(
            NXBTDaemon.WATCHDOG_DEFAULT_TIMEOUT,
            average_ms / 1000 * NXBTDaemon.WATCHDOG_AVERAGE_FACTOR,
        )

    @staticmethod
    def mark_hunting(drive, log_name, kind, reason=""):
        """Append a hunt start/stop marker to the encounter log."""
        try:
            with drive.open(log_name or DEFAULT_ENCOUNTER_LOG, "a") as f:
                f.write(marker_line(kind, reason))
        except Exception:
            logger.exception("Failed to write hunt marker")

    def __init__(self, dman):
        """Create daemon state, its work queue, and the worker process."""
        self.cypi_requests = getattr(dman, "cypi_requests", None)
        self.cypi_replies = getattr(dman, "cypi_replies", None)

        def loop(ns, uns, tqueue, macro_tree, drive):
            """Run the NXBT worker process until its shared run flag clears."""
            logger = logging.getLogger(__name__)
            steps_logger = logging.getLogger(f"{__name__}.steps")
            setup_logging()
            bluetooth = None
            nx = None
            pi = CyPiController(self.cypi_requests, self.cypi_replies, uns)
            controller = None
            playing_gen = None
            playing = None
            disconnected_since = None
            watchdog_since = None
            watchdog_seen_encounter = None
            reset_seen_encounter = None
            reset_due = None
            watchdog_timeout = NXBTDaemon.WATCHDOG_DEFAULT_TIMEOUT
            hunting_log = None
            cypi_connect_count = None

            def select_backend(name):
                ns.backend = name
                uns.controller_backend = name

            async def finish_cypi_connect():
                nonlocal cypi_connect_count
                count = getattr(uns, "cypi_connect_count", 0)
                if count == cypi_connect_count:
                    return
                try:
                    logger.info(
                        "Checking CYNX connection setup (connection %s).", count
                    )
                    await cypi_connect_setup(pi, 0, uns)
                except CyPiStopped:
                    ns.pause = True
                except (OSError, CyPiError) as error:
                    logger.exception("CYNX connection setup failed")
                    ns.pause = True
                    uns.controller_error = str(error)
                finally:
                    cypi_connect_count = count

            async def connect_backend(name):
                nonlocal nx, bluetooth, controller
                select_backend(name)
                if name == "cypi":
                    result = await cypi_request(
                        self.cypi_requests, self.cypi_replies, "connect", timeout=20
                    )
                    nx, controller = pi, 0
                    connected = bool(result.get("switch_connected"))
                    if connected:
                        await finish_cypi_connect()
                    return connected
                if getattr(uns, "cypi_network_connected", False) and (
                    getattr(uns, "cypi_status", {}).get("spoofing")
                ):
                    await cypi_request(
                        self.cypi_requests, self.cypi_replies, "disconnect", timeout=20
                    )
                if bluetooth is None:
                    bluetooth = nxbt.Nxbt()
                nx = bluetooth
                success, controller = await nxbt_connect(nx)
                return success

            async def disconnect_backend():
                nonlocal controller
                if ns.backend == "cypi":
                    await cypi_request(
                        self.cypi_requests, self.cypi_replies, "disconnect", timeout=20
                    )
                    controller = None
                    return True
                return await nxbt_disconnect(nx, controller, uns=uns)

            async def fallback(ready_at=0):
                """Wait for Pi recovery/detach, then resume through normal BT setup."""
                nonlocal controller, playing_gen
                ns.connected = False
                sync_hunt_marker()
                ready_at = max(ready_at, getattr(uns, "cypi_fallback_ready_at", 0))
                while ns.run and time.monotonic() < ready_at:
                    if ns.stop or ns.disconnect:
                        return False
                    await asyncio.sleep(0.1)
                if not ns.run or ns.stop or ns.disconnect:
                    return False
                try:
                    success = await connect_backend("nxbt")
                except Exception:
                    logger.exception("Bluetooth fallback connection failed")
                    success = False
                ns.connected = success
                if success:
                    uns.controller_notice = (
                        "CyPi disconnected; resumed controller playback over Bluetooth."
                    )
                    uns.nxbt_connection_lost = False
                    uns.controller_error = ""
                    return True
                select_backend("none")
                ns.pause = True
                ns.playing = False
                playing_gen = None
                controller = None
                uns.nxbt_connection_lost = True
                uns.controller_error = (
                    "CyPi disconnected and Bluetooth fallback failed."
                )
                return False

            def sync_hunt_marker(shutdown=False):
                """Log a #STOP/#START marker when the hunting state changes."""
                nonlocal hunting_log
                log_name = getattr(uns, "encounter_log", None) or DEFAULT_ENCOUNTER_LOG
                hunting = (
                    not shutdown
                    and ns.loop
                    and ns.connected
                    and not ns.pause
                    and not ns.stop
                )
                if hunting_log is not None and (not hunting or hunting_log != log_name):
                    if shutdown:
                        reason = "shutdown"
                    elif not ns.connected:
                        reason = "disconnected"
                    elif not ns.loop:
                        reason = "stopped"
                    elif hunting_log != log_name:
                        reason = "hunt changed"
                    else:
                        reason = "paused"
                    NXBTDaemon.mark_hunting(drive, hunting_log, STOP_MARKER, reason)
                    hunting_log = None
                if hunting and hunting_log is None:
                    NXBTDaemon.mark_hunting(drive, log_name, START_MARKER)
                    hunting_log = log_name

            async def update_connection():
                """Apply connection requests and detect drops; True skips this tick."""
                nonlocal controller, disconnected_since, playing_gen, nx
                if ns.disconnect:
                    ns.disconnect = False
                    if not ns.connected:
                        return True
                    try:
                        success = await disconnect_backend()
                    except (OSError, CyPiError):
                        logger.exception("Controller disconnect failed")
                        success = False
                    if success:
                        controller = None
                        ns.connected = False
                        select_backend("none")

                if ns.connect:
                    ns.connect = False
                    if ns.connected:
                        return True
                    name = ns.requested_backend
                    if name == "auto":
                        name = (
                            "cypi"
                            if getattr(uns, "cypi_network_connected", False)
                            else "nxbt"
                        )
                    try:
                        success = await connect_backend(name)
                    except Exception as error:
                        logger.exception("Controller connection failed")
                        uns.controller_error = str(error)
                        success = False
                    if success:
                        ns.connected = True
                        uns.controller_error = ""
                        uns.nxbt_connection_lost = False
                        uns.nxbt_connect_failed = False
                        return True
                    else:
                        # Never connected, so this isn't a lost connection
                        uns.nxbt_connect_failed = True
                        logger.error("Couldn't connect the controller.")
                        if name == "nxbt" and nx is not None:
                            await nxbt_disconnect(nx, controller, uns=uns)
                        controller = None
                        ns.connected = False
                        select_backend("none")

                if (
                    not ns.connected
                    and ns.allow_auto_cypi
                    and getattr(uns, "cypi_network_connected", False)
                    and getattr(uns, "cypi_switch_connected", False)
                ):
                    nx, controller = pi, 0
                    select_backend("cypi")
                    await finish_cypi_connect()
                    ns.connected = True

                # Checked before the pause gate so drops are noticed while paused
                if ns.connected and controller is not None:
                    if ns.backend == "cypi":
                        if ns.stop:
                            return False
                        if getattr(uns, "cypi_reconnecting", False):
                            await asyncio.sleep(0.1)
                            return True
                        await finish_cypi_connect()
                        if nx.state[controller]["state"] != "connected":
                            await fallback()
                            return True
                        return False
                    if nx.state[controller]["state"] == "connected":
                        disconnected_since = None
                    else:
                        now = time.monotonic()
                        if disconnected_since is None:
                            disconnected_since = now
                            logger.warning(
                                "Controller left connected state, waiting for recovery..."
                            )
                        if now - disconnected_since >= NXBTDaemon.GRACE_PERIOD:
                            disconnected_since = None
                            uns.nxbt_connection_lost = True
                            uns.controller_error = "Bluetooth controller disconnected."
                            logger.error("Connection lost, disconnecting controller.")
                            await nxbt_disconnect(nx, controller, uns=uns)
                            controller = None
                            ns.connected = False
                            select_backend("none")
                            ns.playing = False
                            playing_gen = None
                            ns.epoch += 1
                            ns.stop = True
                        else:
                            await asyncio.sleep(NXBTDaemon.POLL_RATE)
                        return True
                return False

            def update_restarts():
                """Restart looping macros for watchdog expiry or encounter grace."""
                nonlocal playing_gen, watchdog_since, watchdog_seen_encounter
                nonlocal watchdog_timeout, reset_seen_encounter, reset_due
                # Restart the looping macro if a hunt makes no progress for too long
                now = time.time()
                last_encounter = getattr(uns, "last_encounter_time", None)
                if (
                    ns.loop
                    and ns.connected
                    and not ns.pause
                    and not ns.stop
                    and playing_gen is not None
                ):
                    if (
                        watchdog_since is None
                        or last_encounter != watchdog_seen_encounter
                    ):
                        watchdog_since = now
                        watchdog_seen_encounter = last_encounter
                        watchdog_timeout = NXBTDaemon.watchdog_timeout(
                            drive, getattr(uns, "encounter_log", None)
                        )
                    elif now - watchdog_since >= watchdog_timeout:
                        logger.warning("Watchdog triggered, restarting macro.")
                        playing_gen = playing.walk()
                        uns.watchdog_triggered = True
                        # The flag above is cleared once reported; these persist
                        uns.watchdog_count = getattr(uns, "watchdog_count", 0) + 1
                        uns.watchdog_at = now
                        watchdog_since = now
                else:
                    watchdog_since = None

                # Loop the macro from the start a grace period after an encounter
                if (
                    uns.encounter_reset
                    and ns.loop
                    and ns.connected
                    and not ns.pause
                    and not ns.stop
                    and not uns.nxbt_daemon_stop
                    and playing_gen is not None
                ):
                    if last_encounter != reset_seen_encounter:
                        reset_seen_encounter = last_encounter
                        reset_due = (
                            now + NXBTDaemon.ENCOUNTER_GRACE
                            if last_encounter is not None
                            else None
                        )
                    elif reset_due is not None and now >= reset_due:
                        logger.info("Encounter grace elapsed, restarting macro.")
                        playing_gen = playing.walk()
                        reset_due = None
                else:
                    reset_seen_encounter = last_encounter
                    reset_due = None

            async def play_next():
                """Advance playback once, or dequeue a macro from the current epoch."""
                nonlocal playing, playing_gen
                if ns.connected:
                    # Keep playing current Macro
                    if playing_gen is not None:
                        try:
                            _input = next(playing_gen)
                            steps_logger.debug(f"Playing {str(_input)}")
                            try:
                                next_step = await _input.play(nx, controller, uns=uns)
                            except CyPiUnavailable as error:
                                if not await fallback(error.ready_at):
                                    return
                                next_step = None
                                if not error.completed:
                                    next_step = await _input.play(
                                        nx, controller, uns=uns
                                    )
                            if next_step is not None:
                                playing_gen = next_step.walk()
                        except CyPiStopped:
                            ns.playing = False
                            playing_gen = None
                        except StopIteration:
                            ns.playing = False
                            playing_gen = None
                            if ns.loop:
                                tqueue.put((ns.epoch, str(playing)))
                        except Exception as error:
                            logger.exception("Macro playback failed")
                            ns.playing = False
                            ns.pause = True
                            uns.controller_error = str(error)
                            uns.controller_notice = (
                                f"Controller playback stopped: {error}"
                            )
                            playing_gen = None
                        return
                elif playing_gen is not None:
                    ns.playing = False
                    playing_gen = None

                try:
                    epoch, _input = tqueue.get_nowait()
                    # Queued before the last stop/clear
                    if epoch != ns.epoch or not isinstance(_input, str):
                        return
                    playing = Macro(_input)
                    playing_gen = playing.walk()
                    ns.playing = True
                except Empty:
                    await asyncio.sleep(NXBTDaemon.POLL_RATE)

            async def cleanup():
                """Persist macros, disconnect NXBT, and mark its process safe to reap."""
                sync_hunt_marker(shutdown=True)
                try:
                    save_macros(drive)
                    if ns.connected:
                        await disconnect_backend()
                except Exception:
                    logger.exception("NXBT shutdown cleanup failed")
                finally:
                    # NXBT only cleans up from atexit, which a terminated daemon
                    # skips, leaving its controller and manager processes behind
                    try:
                        if bluetooth is not None:
                            bluetooth._on_exit()
                    except Exception:
                        logger.exception("NXBT process cleanup failed")
                    # Mark process safe to boom
                    self.ns.done = True
                    uns.controller_backend = "none"

            async def main_task():
                """Handle controller connection, macro playback, and shutdown."""
                nonlocal playing_gen
                Macro.bind_macro_tree(macro_tree)
                load_macros(drive)
                try:
                    os.setpriority(os.PRIO_PROCESS, 0, -20)
                except PermissionError:
                    logger.warning(
                        "Failed to elevate NXBTDaemon priority. Run with sudo."
                    )
                while ns.run:
                    sync_hunt_marker()
                    if await update_connection():
                        continue
                    # Keep restart bookkeeping before stop/pause gates to reset stale timers.
                    update_restarts()
                    if ns.stop:
                        # Abort the current macro; stale queued items are dropped by epoch
                        playing_gen = None
                        ns.playing = False
                        ns.stop = False
                        continue
                    if ns.pause or not ns.connected:
                        await asyncio.sleep(NXBTDaemon.POLL_RATE)
                        continue
                    if uns.nxbt_daemon_stop:
                        await Macro("hold c").play(nx, controller)
                        ns.pause = True
                        continue
                    await play_next()
                await cleanup()

            asyncio.run(main_task())

        self.tqueue = multiprocessing.Queue()
        macro_tree = dman.manager.dict()
        Macro.bind_macro_tree(macro_tree)
        super().__init__(dman, self.tqueue, macro_tree, dman.drive)
        self.ns.done = False
        self.ns.loop = False
        self.ns.connect = False
        self.ns.disconnect = False
        self.uns.nxbt_daemon_stop = False
        self.uns.pressed_buttons = []
        self.ns.connected = False
        self.ns.backend = "none"
        self.ns.requested_backend = "auto"
        self.ns.allow_auto_cypi = bool(
            dman.context.config.get("cypi_auto_connect", True)
        )
        self.uns.controller_backend = "none"
        self.uns.controller_error = ""
        self.uns.controller_notice = ""
        self.uns.nxbt_connection_lost = False
        self.uns.nxbt_connect_failed = False
        self.uns.watchdog_triggered = False
        self.uns.watchdog_count = 0
        self.uns.watchdog_at = None
        # Ternary branches that mean the macro got lost and is recovering
        self.uns.failsafe_macros = [
            str(name).replace("-", "_")
            for name in dman.context.config.get("failsafe_macros", None) or []
        ]
        self.uns.failsafe_count = 0
        self.uns.failsafe_at = None
        self.uns.encounter_reset = bool(
            dman.context.config.get("encounter_reset", True)
        )
        self.uns.last_encounter_time = None
        self.uns.match_scene_id = None
        self.uns.scene_matched = False
        self.ns.playing = False
        self.ns.pause = True
        self.ns.stop = False
        self.ns.epoch = 0
        self.loop = loop
        self.start(daemon=False)

    def queue(self, macro):
        """Add a macro definition to the playback queue."""
        self.tqueue.put((self.ns.epoch, str(macro)))

    def stop(self):
        """Stop playback, pause execution, and invalidate everything queued."""
        self.ns.epoch += 1
        self.ns.stop = True
        self.ns.pause = True
        self.ns.loop = False
        if self.cypi_requests is not None:
            self.cypi_requests.put({"id": None, "command": "stop"})

    def unpause(self):
        """Resume playback and clear pending stop notifications."""
        self.ns.pause = False
        self.uns.nxbt_daemon_stop = False
        self.uns.messaged = False

    def pause(self):
        """Pause playback without clearing the queue."""
        self.ns.pause = True

    def set_loop(self, *, loop=True):
        """Set whether completed macros are added back to the queue."""
        self.ns.loop = loop
        if loop:
            self.ns.pause = True

    async def connect(self, backend=None):
        """Request a controller connection and wait for its result."""
        if backend is not None and backend not in ("cypi", "nxbt"):
            raise ValueError("Unknown controller backend.")
        if self.ns.connected:
            if backend is None or self.ns.backend == backend:
                return True
            self.stop()
            if not await self.disconnect():
                return False
        self.ns.requested_backend = backend or "auto"
        self.ns.allow_auto_cypi = backend != "nxbt"
        self.ns.connect = True
        self.uns.nxbt_connect_failed = False
        self.uns.nxbt_connection_lost = False

        try:
            async with asyncio.timeout(30):
                while not (
                    self.ns.connected
                    or self.uns.nxbt_connect_failed
                    or self.uns.nxbt_connection_lost
                ):
                    await asyncio.sleep(5)
        except TimeoutError:
            return False
        return self.ns.connected

    async def disconnect(self, backend=None):
        """Request a controller disconnection and wait for completion."""
        if backend == "cypi" and self.ns.backend != "cypi":
            try:
                await cypi_request(
                    self.cypi_requests, self.cypi_replies, "disconnect", timeout=20
                )
                return True
            except (OSError, CyPiError):
                return False
        if backend == "nxbt" and self.ns.backend != "nxbt":
            return True
        self.ns.allow_auto_cypi = False
        self.stop()
        if (
            self.ns.backend != "cypi" or not self.ns.connected
        ) and self.cypi_requests is not None:
            self.cypi_requests.put({"id": None, "command": "disconnect"})
        self.ns.disconnect = True
        try:
            async with asyncio.timeout(45):
                while self.ns.connected:
                    await asyncio.sleep(1)
        except TimeoutError:
            return False
        return True

    @property
    def connected(self):
        """Return whether the worker reports an active controller connection."""
        return self.ns.connected

    @property
    def backend(self):
        """Return the active transport without exposing NXBT-specific internals."""
        return self.ns.backend

    async def clear_queue(self):
        """Stop playback, wait for the queue to clear, and resume the daemon."""
        self.stop()
        try:
            async with asyncio.timeout(30):
                while self.ns.stop:
                    await asyncio.sleep(1)
        except TimeoutError:
            return False
        self.unpause()
        return True
