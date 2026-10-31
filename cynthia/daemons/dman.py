"""Discover, start, stop, and reload daemon processes."""

import asyncio
import importlib
import logging
import sys
import time
from multiprocessing import Manager, shared_memory
from pathlib import Path

import numpy
from discord import app_commands

from cynthia.utils.drive import Drive
from cynthia.utils.namespace import Namespace

from .daemon import Daemon

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


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
        self.fb = (
            shared_memory.SharedMemory(create=True, size=FB0.nbytes()),
            shared_memory.SharedMemory(create=True, size=FB0.nbytes()),
        )
        self.fbptr = None
        self.pending_state = {}
        self._last_restart = {}
        self._needs_restart = set()
        self.manager = Manager()
        self.uns = self.manager.Namespace()
        self.uns.fbptr = None
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
            if module.stem not in ["__init__", "dman", "daemon"]
        ]
        logger.debug(
            f"{len(self.modules)} daemon modules found in {self.daemon_directory}."
        )
        errors = []
        for module in self.modules:
            logger.debug(f"Loading daemons from module: {module} ...")
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
                logger.error(error)
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
                        logger.warn(f'Duplicate daemon with name "{daemon.__name__}".')
                    self.__loaded_daemons[daemon.__name__] = daemon
                logger.debug("Done")
            else:
                logger.error(f" ERR.\n\tNo daemon found in module: {module}")
        return len(self.loaded_daemons), errors

    def run_daemons(self, *, daemons=None):
        """Start all loaded daemons or only the named daemons."""
        if daemons is not None:
            for _daemon in daemons:
                if _daemon not in self.__loaded_daemons:
                    logger.error(f" ERR. Specified daemon `{_daemon}` not loaded.")
                    continue
                if _daemon not in self.__running_daemons:
                    self.__running_daemons[_daemon] = self.loaded_daemons[_daemon](self)
                else:
                    logger.error(f" ERR. Specified daemon `{_daemon}` already running.")
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
        if daemons is None:
            daemons = list(self.__running_daemons.keys())
        daemons = [
            d for d in daemons if self.__running_daemons.get(d, None) is not None
        ]
        for _daemon in daemons:
            self.__running_daemons[_daemon].ns.run = False
        try:
            async with asyncio.timeout(30):
                while any(
                    self.__running_daemons[_daemon].process.is_alive()
                    and not getattr(self.__running_daemons[_daemon].ns, "done", False)
                    for _daemon in daemons
                ):
                    logger.info(
                        f"Still waiting for daemon(s) {list(filter(lambda k: self.__running_daemons[k].process.is_alive() and not getattr(self.__running_daemons[k].ns,'done', False), self.__running_daemons.keys()))} to close..."
                    )
                    await asyncio.sleep(5)
        except TimeoutError:
            logger.error(" ERR. Some daemon(s) failed to stop.")

        for _daemon in daemons:
            daemon_obj = self.__running_daemons.get(_daemon, None)
            if daemon_obj is None:
                continue
            if daemon_obj.process.is_alive():
                if getattr(daemon_obj.ns, "done", False):
                    logger.info(f"Terminating non-daemon process `{_daemon}`.")
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
            for key in ("uvc_time0", "uvc_time1"):
                frame_time = getattr(self.uns, key, None)
                if frame_time is not None:
                    last = max(last, frame_time / 1e9)
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
            except Exception:
                logger.exception("Daemon monitor error.")
            await asyncio.sleep(1)

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
