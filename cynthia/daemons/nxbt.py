"""Daemon that connects to Nintendo Switch and plays queued macros."""

import asyncio
import logging
import multiprocessing
import os
import time
from queue import Empty

import nxbt

from cynthia.utils.encounters import (
    DEFAULT_ENCOUNTER_LOG,
    START_MARKER,
    STOP_MARKER,
    average_interval_ms,
    marker_line,
)
from cynthia.utils.nxbt_utils import (
    Macro,
    load_macros,
    nxbt_connect,
    nxbt_disconnect,
    save_macros,
)

from .daemon import Daemon

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class NXBTDaemon(Daemon):
    """Manage NXBT connection state and execute queued controller macros."""

    POLL_RATE = 0.5
    GRACE_PERIOD = 5.0
    WATCHDOG_DEFAULT_TIMEOUT = 600.0
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

        def loop(ns, uns, tqueue, macro_tree, drive):
            """Run the NXBT worker process until its shared run flag clears."""
            logger = logging.getLogger(__name__)
            logging.basicConfig(level=logging.DEBUG)
            logging.getLogger("nxbt").setLevel(logging.INFO)
            nx = nxbt.Nxbt()
            controller = None
            playing_gen = None
            playing = None
            disconnected_since = None
            watchdog_since = None
            watchdog_seen_encounter = None
            watchdog_timeout = NXBTDaemon.WATCHDOG_DEFAULT_TIMEOUT
            hunting_log = None

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

            async def main_task():
                """Handle controller connection, macro playback, and shutdown."""
                nonlocal controller
                nonlocal playing_gen
                nonlocal playing
                nonlocal disconnected_since
                nonlocal watchdog_since
                nonlocal watchdog_seen_encounter
                nonlocal watchdog_timeout
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
                    if ns.disconnect:
                        ns.disconnect = False
                        if not ns.connected:
                            continue
                        success = await nxbt_disconnect(nx, controller)
                        if success:
                            controller = None
                            ns.connected = False

                    if ns.connect:
                        ns.connect = False
                        if ns.connected:
                            continue
                        success, controller = await nxbt_connect(nx)
                        if success:
                            ns.connected = True
                            uns.nxbt_connection_lost = False
                            continue
                        else:
                            uns.nxbt_connection_lost = True
                            logger.error("Connection lost, disconnecting controller.")
                            await nxbt_disconnect(nx, controller)
                            controller = None
                            ns.connected = False

                    # Checked before the pause gate so drops are noticed while paused
                    if ns.connected and controller is not None:
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
                                logger.error(
                                    "Connection lost, disconnecting controller."
                                )
                                await nxbt_disconnect(nx, controller)
                                controller = None
                                ns.connected = False
                                ns.playing = False
                                playing_gen = None
                                ns.epoch += 1
                                ns.stop = True
                            else:
                                await asyncio.sleep(NXBTDaemon.POLL_RATE)
                            continue

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
                            watchdog_since = now
                    else:
                        watchdog_since = None

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

                    if ns.connected:
                        # Keep playing current Macro
                        if playing_gen is not None:
                            try:
                                _input = next(playing_gen)
                                logger.debug(f"Playing {str(_input)}")
                                next_step = await _input.play(nx, controller, uns=uns)
                                if next_step is not None:
                                    playing_gen = next_step.walk()
                            except StopIteration:
                                ns.playing = False
                                playing_gen = None
                                if ns.loop:
                                    tqueue.put((ns.epoch, str(playing)))
                            except Exception:
                                logger.exception("Macro playback failed")
                                ns.playing = False
                                playing_gen = None
                            continue
                    elif playing_gen is not None:
                        ns.playing = False
                        playing_gen = None

                    try:
                        epoch, _input = tqueue.get_nowait()

                        # Queued before the last stop/clear
                        if epoch != ns.epoch or not isinstance(_input, str):
                            continue

                        playing = Macro(_input)
                        playing_gen = playing.walk()
                        ns.playing = True

                    except Empty:
                        await asyncio.sleep(NXBTDaemon.POLL_RATE)

                sync_hunt_marker(shutdown=True)
                try:
                    save_macros(drive)
                    if ns.connected:
                        await nxbt_disconnect(nx, controller)
                except Exception:
                    logger.exception("NXBT shutdown cleanup failed")
                finally:
                    # Mark process safe to boom
                    self.ns.done = True

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
        self.ns.connected = False
        self.uns.nxbt_connection_lost = False
        self.uns.watchdog_triggered = False
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

    async def connect(self):
        """Request a controller connection and wait for its result."""
        self.ns.connect = True

        try:
            async with asyncio.timeout(30):
                while not (self.ns.connected or self.uns.nxbt_connection_lost):
                    await asyncio.sleep(5)
        except TimeoutError:
            return False
        return self.ns.connected

    async def disconnect(self):
        """Request a controller disconnection and wait for completion."""
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
