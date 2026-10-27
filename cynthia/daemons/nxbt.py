"""Daemon that connects to Nintendo Switch and plays queued macros."""

import asyncio
import logging
import multiprocessing
import os
import time
from queue import Empty

import nxbt

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

            async def main_task():
                """Handle controller connection, macro playback, and shutdown."""
                nonlocal controller
                nonlocal playing_gen
                nonlocal playing
                nonlocal disconnected_since
                Macro.bind_macro_tree(macro_tree)
                load_macros(drive)

                try:
                    os.setpriority(os.PRIO_PROCESS, 0, -20)
                except PermissionError:
                    logger.warning(
                        "Failed to elevate NXBTDaemon priority. Run with sudo."
                    )

                while ns.run:
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
                                ns.stop = True
                            else:
                                await asyncio.sleep(NXBTDaemon.POLL_RATE)
                            continue

                    if not ns.stop:
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
                                await _input.play(nx, controller)
                            except StopIteration:
                                ns.playing = False
                                playing_gen = None
                                if ns.loop:
                                    tqueue.put(str(playing))
                            continue
                    elif playing_gen is not None:
                        ns.playing = False
                        playing_gen = None

                    try:
                        _input = tqueue.get_nowait()

                        if _input is None:
                            # Poison Pill marks when the stop signal was sent
                            if ns.stop:
                                ns.stop = False
                            continue

                        # If stop signal, loop over queue until poison pill or queue is empty
                        if ns.stop:
                            continue

                        if not isinstance(_input, str):
                            # TODO logger error
                            continue

                        playing = Macro(_input)
                        playing_gen = playing.walk()
                        ns.playing = True

                    except Empty:
                        if ns.stop:
                            ns.stop = False
                        await asyncio.sleep(NXBTDaemon.POLL_RATE)

                save_macros(drive)

                if ns.connected:
                    await nxbt_disconnect(nx, controller)

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
        self.ns.playing = False
        self.ns.pause = True
        self.ns.stop = False
        self.loop = loop
        self.start(daemon=False)

    def queue(self, macro):
        """Add a macro definition to the playback queue."""
        self.tqueue.put(str(macro))

    def stop(self):
        """Stop playback, pause execution, and signal the worker to drain."""
        self.ns.stop = True
        self.ns.pause = True
        self.ns.loop = False
        self.tqueue.put(None)

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
