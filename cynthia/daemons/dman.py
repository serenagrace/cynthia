"""Discover, start, stop, and reload daemon processes."""

import asyncio
import importlib
import logging
import sys
import time
from multiprocessing import Manager, Queue
from pathlib import Path

import numpy
from discord import app_commands

from cynthia.utils.drive import Drive
from cynthia.utils.namespace import Namespace
from cynthia.utils.streamcfg import init_settings, shows_no_signal

from .daemon import Daemon
from .frames import AudioRing, FrameRing

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

DEFAULT_FREEZE_SECONDS = 120
# Each failed repair doubles the wait before the next, up to this many times
FREEZE_MAX_DOUBLINGS = 4
# Picture changes needed after a repair before the capture counts as recovered;
# a reset card shows a few black or no-signal frames before any frozen picture
FREEZE_RECOVER_CHANGES = 5
# DM the owner again when this many repairs in a row have not helped
FREEZE_ESCALATE_ATTEMPTS = 3
# Frames older than this are a stall, not a freeze
FREEZE_FRESH_SECONDS = 5


def describe_seconds(seconds):
    """Format a duration for an owner DM, e.g. "45 s" or "12 min"."""
    if seconds < 120:
        return f"{seconds:.0f} s"
    return f"{seconds / 60:.0f} min"


class FreezeWatch:
    """Notice a capture that keeps publishing one identical picture.

    The stall check only sees frames stop arriving. A hung capture card can
    keep delivering frames whose content never changes; their hash then stays
    the same while their timestamps advance.
    """

    def __init__(self):
        """Start with no picture seen."""
        self.hash = None
        self.since = None
        self.frozen_at = None
        self.attempts = 0
        self.changes = 0

    def update(self, frame_hash, now, timeout, excused=False):
        """Feed the newest frame hash; return "frozen", "recovered" or None.

        `excused` marks moments a static picture is expected (the card's
        no-signal screen, or no fresh frames, which the stall check handles).
        "frozen" means a repair is due now; waits double after each failure.
        """
        if timeout <= 0 or not frame_hash:
            self.__init__()
            return None
        if frame_hash != self.hash:
            self.hash, self.since = frame_hash, now
            if self.frozen_at is None:
                return None
            self.changes += 1
            if self.changes < FREEZE_RECOVER_CHANGES:
                return None
            self.frozen_at = None
            self.attempts = 0
            self.changes = 0
            return "recovered"
        if excused or self.since is None:
            self.since = now
            return None
        wait = timeout * 2 ** min(self.attempts, FREEZE_MAX_DOUBLINGS)
        if now - self.since < wait:
            return None
        if self.frozen_at is None:
            self.frozen_at = self.since
        self.attempts += 1
        self.changes = 0
        self.since = now
        return "frozen"


class FB0:
    """Dimensions and buffer helpers for captured video frames."""

    WIDTH = 1920
    HEIGHT = 1080
    CHANNELS = 3

    @staticmethod
    def nbytes():
        """Return the byte size of one RGB frame buffer."""
        return FB0.WIDTH * FB0.HEIGHT * FB0.CHANNELS * numpy.dtype(numpy.uint8).itemsize

    @staticmethod
    def shape():
        """Return the array shape for one RGB frame buffer."""
        return (FB0.HEIGHT, FB0.WIDTH, FB0.CHANNELS)

    @staticmethod
    def native_shape():
        """Return the array shape of one NV12 frame: Y plane, then interleaved UV."""
        return (FB0.HEIGHT * 3 // 2, FB0.WIDTH)


class DMan:
    """Manage daemon discovery, shared frame buffers, and process lifecycle."""

    RELOADABLE = ("CYStream", "UVCDaemon")
    RESTARTABLE = ("UVCDaemon", "CVDaemon")
    STALL_TIMEOUT = 30
    RESTART_BACKOFF = 10

    def __init__(self, context):
        """Create shared state, discover daemons, and start loaded daemons."""
        self.context = context
        self.drive = Drive(self.context.drive_path)
        self.__modules = list()
        self.__loaded_modules = list()
        self.__loaded_daemons = Namespace()
        self.__running_daemons = Namespace()
        self.__previously_loaded_modules = list()
        self.ring = FrameRing(FB0.shape())
        # The card's own NV12, kept so encoders skip the BGR round trip
        self.native_ring = FrameRing(FB0.native_shape())
        self.audio_ring = AudioRing()
        self.pending_state = {}
        self._last_restart = {}
        self._needs_restart = set()
        self.freeze_watch = FreezeWatch()
        # Bot sets this to an `async (text, alert)` that DMs the owner
        self.notify = None
        self.manager = Manager()
        self.uns = self.manager.Namespace()
        self.cypi_requests = Queue()
        self.cypi_replies = self.manager.dict()
        self.cypi_alerts = self.manager.Queue(100)
        self.uns.controller_backend = "none"
        init_settings(self.uns, self.context.config)
        self.load_daemons()
        self.run_daemons()

    def load_daemons(self):
        """Import daemon modules and register their daemon subclasses."""
        importlib.invalidate_caches()
        self.clear_daemons()

        self.__directory = Path(__file__).parent
        self.__modules = [
            module.stem
            for module in Path(__file__).parent.glob("*.py")
            if module.stem not in ["__init__", "dman", "daemon", "frames"]
        ]
        logger.debug(
            f"Loading {len(self.modules)} daemon modules from {self.daemon_directory}:"
        )
        errors = []
        for module in self.modules:
            daemons_module = None
            try:
                if module in self.__previously_loaded_modules:
                    daemons_module = importlib.reload(
                        sys.modules[f"cynthia.daemons.{module}"]
                    )
                else:
                    daemons_module = importlib.import_module(
                        "." + module, "cynthia.daemons"
                    )
                self.__loaded_modules.append(module)
            except (ImportError, FileNotFoundError, ValueError, KeyError) as e:
                error = (
                    f" ERR.\n\tFailed to load daemon from module: {module}\n"
                    + f"\tError: {e}"
                )
                logger.error(f"Failed to load daemon module `{module}`: {e}")
                errors += error
            if daemons_module is not None:
                public_objects = filter(
                    lambda key: not key.startswith("__"), dir(daemons_module)
                )
                daemons = filter(
                    lambda obj: isinstance(obj, type) and issubclass(obj, Daemon),
                    [getattr(daemons_module, key) for key in public_objects],
                )
                for daemon in daemons:
                    if daemon.__name__ == "Daemon":
                        continue
                    if daemon.__name__ in self.__loaded_daemons:
                        logger.warning(
                            f'Duplicate daemon with name "{daemon.__name__}".'
                        )
                    self.__loaded_daemons[daemon.__name__] = daemon
                logger.debug(f"  `{module}`")
            else:
                logger.error(f"No daemon found in module: `{module}`")
        return len(self.loaded_daemons), errors

    def run_daemons(self, *, daemons=None):
        """Start all loaded daemons or only the named daemons."""
        if daemons is not None:
            for _daemon in daemons:
                if _daemon not in self.__loaded_daemons:
                    logger.error(f"Specified daemon `{_daemon}` not loaded.")
                    continue
                if _daemon not in self.__running_daemons:
                    self.__running_daemons[_daemon] = self.loaded_daemons[_daemon](self)
                else:
                    logger.error(f"Specified daemon `{_daemon}` already running.")
            return

        for name, daemon in self.loaded_daemons.items():
            # if name in ("CYStream",):
            #    continue
            if name not in self.__running_daemons:
                self.__running_daemons[name] = daemon(self)

    def clear_daemons(self):
        """Reset discovered daemon classes while retaining modules for reload."""
        self.__previously_loaded_modules = getattr(self, "__loaded_modules", list())
        self.__loaded_modules = list()
        self.__loaded_daemons = Namespace()

    async def stop_daemons(self, *, daemons=None):
        """Signal selected daemons to stop and clean up their processes."""
        stopping_all = daemons is None
        if stopping_all:
            daemons = list(self.__running_daemons.keys())
        daemons = [
            d for d in daemons if self.__running_daemons.get(d, None) is not None
        ]
        if "NXBTDaemon" in daemons and "CyPiDaemon" in daemons:
            # NXBT needs the transport alive for its final disconnect.
            await self.stop_daemons(daemons=["NXBTDaemon"])
            daemons.remove("NXBTDaemon")
        for _daemon in daemons:
            if _daemon == "NXBTDaemon":
                self.__running_daemons[_daemon].stop()
            self.__running_daemons[_daemon].ns.run = False
        try:
            async with asyncio.timeout(30):
                while any(
                    self.__running_daemons[_daemon].process.is_alive()
                    and not getattr(self.__running_daemons[_daemon].ns, "done", False)
                    for _daemon in daemons
                ):
                    logger.debug(
                        f"Still waiting for daemon(s) {list(filter(lambda k: self.__running_daemons[k].process.is_alive() and not getattr(self.__running_daemons[k].ns,'done', False), daemons))} to close..."
                    )
                    await asyncio.sleep(5)
        except TimeoutError:
            logger.error("Some daemon(s) failed to stop.")

        for _daemon in daemons:
            daemon_obj = self.__running_daemons.get(_daemon, None)
            if daemon_obj is None:
                continue
            if daemon_obj.process.is_alive():
                if getattr(daemon_obj.ns, "done", False):
                    logger.debug(f"Terminating non-daemon process `{_daemon}`.")
                    daemon_obj.process.terminate()
                    daemon_obj.process.join()
                    self._forget(_daemon)
                    continue
                logger.error(f"Daemon `{_daemon}` failed to stop.")
                if daemon_obj.process.daemon:
                    daemon_obj.process.terminate()
                    daemon_obj.process.join()
                    self._forget(_daemon)
                continue
            self._forget(_daemon)
        if stopping_all and not self.__running_daemons:
            self.ring.close(unlink=True)
            self.native_ring.close(unlink=True)
            self.audio_ring.close()
            # Without this the shared-state manager process outlives the bot
            self.manager.shutdown()

    def _forget(self, name):
        """Drop a stopped daemon and shut down its namespace manager."""
        daemon_obj = self.__running_daemons.pop(name, None)
        close = getattr(daemon_obj, "close", None)
        if close is not None:
            try:
                close()
            except Exception:
                logger.exception(f"Failed to close manager for daemon `{name}`.")

    def reap_exited_daemons(self):
        """Join exited daemon processes and return names that exited unexpectedly."""
        unexpected = []
        for name, daemon_obj in list(self.__running_daemons.items()):
            if daemon_obj.process.is_alive():
                continue
            daemon_obj.process.join()
            if daemon_obj.ns.run:
                daemon_obj.ns.run = False
                unexpected.append(name)
                logger.error(
                    f"Daemon `{name}` exited unexpectedly with code "
                    f"{daemon_obj.process.exitcode}."
                )
        return unexpected

    def stalled_daemons(self, now=None):
        """Return names of live capture/CV daemons that stopped producing data."""
        now = time.time() if now is None else now
        stalled = []
        uvc = self.__running_daemons.get("UVCDaemon", None)
        if uvc is not None and uvc.process.is_alive() and uvc.ns.run:
            last = getattr(uvc, "started_at", now)
            last = max(last, self.ring.last_time_ns / 1e9)
            if now - last > self.STALL_TIMEOUT:
                stalled.append("UVCDaemon")
        cv = self.__running_daemons.get("CVDaemon", None)
        if cv is not None and cv.process.is_alive() and cv.ns.run:
            beat = getattr(cv.ns, "heartbeat", None)
            if beat is not None:
                beat = max(beat, getattr(cv, "started_at", beat))
                if now - beat > self.STALL_TIMEOUT:
                    stalled.append("CVDaemon")
        return stalled

    async def restart_daemon(self, name):
        """Kill one daemon process and start a fresh one with its saved state."""
        daemon_obj = self.__running_daemons.get(name, None)
        if daemon_obj is None:
            return False
        state = daemon_obj.snapshot_state()
        daemon_obj.ns.run = False
        process = daemon_obj.process
        if process.is_alive():
            process.terminate()
            await asyncio.to_thread(process.join, 5)
        if process.is_alive():
            process.kill()
            await asyncio.to_thread(process.join, 5)
        if process.is_alive():
            logger.error(f"Daemon `{name}` will not die; cannot restart it.")
            return False
        self._forget(name)
        self.pending_state[name] = state
        self.run_daemons(daemons=[name])
        return True

    async def monitor_daemons(self):
        """Restart capture/CV daemons that exit or stall while the bot runs."""
        while True:
            try:
                self._needs_restart.update(self.reap_exited_daemons())
                self._needs_restart.update(self.stalled_daemons())
                for name in sorted(self._needs_restart):
                    if name not in self.RESTARTABLE:
                        self._needs_restart.discard(name)
                        continue
                    now = time.monotonic()
                    if now - self._last_restart.get(name, -1e9) < self.RESTART_BACKOFF:
                        continue
                    self._last_restart[name] = now
                    logger.error(f"Daemon `{name}` dead or stalled; restarting.")
                    if await self.restart_daemon(name):
                        self._needs_restart.discard(name)
                if "UVCDaemon" not in self._needs_restart:
                    await self.watch_capture_freeze()
            except Exception:
                logger.exception("Daemon monitor error.")
            await asyncio.sleep(1)

    async def watch_capture_freeze(self, now=None):
        """Reset the capture card when its picture stops changing, and tell the owner.

        Returns the `FreezeWatch` event ("frozen", "recovered" or None).
        """
        now = time.time() if now is None else now
        uvc = self.__running_daemons.get("UVCDaemon", None)
        if uvc is None or not uvc.process.is_alive():
            return None
        timeout = float(
            self.context.config.get("capture_freeze_seconds", DEFAULT_FREEZE_SECONDS)
        )
        watch = self.freeze_watch
        frozen_at = watch.frozen_at
        # Stale frames are the stall check's job; only a moving clock counts here
        stale = now - self.ring.last_time_ns / 1e9 > FREEZE_FRESH_SECONDS
        event = watch.update(
            self.ring.last_hash,
            now,
            timeout,
            excused=stale or shows_no_signal(self.uns),
        )
        if event == "frozen":
            frozen_for = describe_seconds(now - watch.frozen_at)
            logger.error(
                "Capture picture unchanged for %s while frames keep arriving; "
                "resetting the capture card (attempt %d).",
                frozen_for,
                watch.attempts,
            )
            if watch.attempts == 1:
                await self._notify(
                    f"🧊 The capture picture has been frozen for {frozen_for} "
                    "while frames kept arriving. Resetting the capture card.",
                    alert=True,
                )
            elif watch.attempts == FREEZE_ESCALATE_ATTEMPTS:
                await self._notify(
                    f"🧊 The capture is still frozen after {watch.attempts} card "
                    f"resets ({frozen_for}). Check the Switch and the HDMI cable; "
                    "resets will continue, less often.",
                    alert=True,
                )
            self._last_restart["UVCDaemon"] = time.monotonic()
            await self.restart_daemon("UVCDaemon")
        elif event == "recovered":
            logger.info("Capture picture is moving again.")
            await self._notify(
                "✅ The capture picture is moving again after "
                f"{describe_seconds(now - frozen_at)}."
            )
        return event

    async def _notify(self, text, alert=False):
        """DM the owner through the bot, never letting a Discord error escape."""
        if self.notify is None:
            return
        try:
            await self.notify(text, alert)
        except Exception:
            logger.exception("Couldn't notify the owner.")

    async def reload_daemon(self, name):
        """Stop one daemon, reload its module from disk and start it again."""
        if name not in self.RELOADABLE:
            raise ValueError(f"Daemon `{name}` is not reloadable.")
        daemon_cls = self.__loaded_daemons.get(name, None)
        if daemon_cls is None:
            raise ValueError(f"Daemon `{name}` is not loaded.")

        # Import the new code first so a syntax error leaves the old daemon running
        old_module = sys.modules[daemon_cls.__module__]
        try:
            module = importlib.reload(old_module)
            new_cls = getattr(module, name)
        except Exception:
            logger.exception(f"Failed to reload module for daemon `{name}`.")
            raise

        running = self.__running_daemons.get(name, None)
        if running is not None:
            self.pending_state[name] = running.snapshot_state()
        await self.stop_daemons(daemons=[name])
        if name in self.__running_daemons:
            raise RuntimeError(f"Daemon `{name}` failed to stop.")
        self.__loaded_daemons[name] = new_cls
        self.run_daemons(daemons=[name])

    @property
    def modules(self):
        """Return discovered daemon module names."""
        return self.__modules

    @property
    def loaded_modules(self):
        """Return daemon module names imported successfully."""
        return self.__loaded_modules

    @property
    def daemon_directory(self):
        """Return the directory used to discover daemon modules."""
        return self.__directory

    @property
    def loaded_daemons(self):
        """Return the mapping of registered daemon classes."""
        return self.__loaded_daemons

    @property
    def running_daemons(self):
        """Return the mapping of active daemon instances."""
        return self.__running_daemons


def daemon_running(daemon: str):
    """Create a command check that requires a named daemon to be running."""

    async def predicate(interaction):
        """Check whether the interaction's client has the named daemon."""
        if hasattr(interaction.client, "dman"):
            return daemon in interaction.client.dman.running_daemons
        return False

    return app_commands.check(predicate)
