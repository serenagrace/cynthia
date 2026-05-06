import asyncio
import nxbt
import multiprocessing
from cynthia.utils.nxbt_utils import Macro, nxbt_connect, nxbt_disconnect
from .daemon import Daemon
from queue import Empty
import os
import signal


class NXBTDaemon(Daemon):
    POLL_RATE = 0.5

    def __init__(self, dman):
        def loop(ns, uns, tqueue):
            nx = nxbt.Nxbt()
            controller = None
            playing_gen = None
            playing = None

            async def main_task():
                nonlocal controller
                nonlocal playing_gen
                nonlocal playing
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
                            continue

                    if not ns.stop:
                        if ns.pause or not ns.connected:
                            await asyncio.sleep(NXBTDaemon.POLL_RATE)
                            continue

                        # Keep playing current Macro
                        if playing_gen is not None:
                            try:
                                await next(playing_gen)(nx, controller)
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

                if ns.connected:
                    await nxbt.disconnect(nx, controller)

                # Mark process safe to boom
                self.ns.done = True

            asyncio.run(main_task())

        self.tqueue = multiprocessing.Queue()
        super().__init__(dman, self.tqueue)
        self.ns.done = False
        self.ns.loop = False
        self.ns.connect = False
        self.ns.disconnect = False
        self.ns.connected = False
        self.ns.playing = False
        self.ns.pause = True
        self.ns.stop = False
        self.loop = loop
        self.start(daemon=False)

    def queue(self, macro):
        self.tqueue.put(str(macro))

    def stop(self):
        self.ns.stop = True
        self.ns.pause = True
        self.ns.loop = False
        self.tqueue.put(None)

    def unpause(self):
        self.ns.pause = False

    def pause(self):
        self.ns.pause = True

    def loop(self, *, loop=True):
        self.ns.loop = loop

    async def connect(self):
        self.ns.connect = True

        try:
            async with asyncio.timeout(30):
                while not self.ns.connected:
                    await asyncio.sleep(1)
        except TimeoutError:
            return False
        return True

    async def disconnect(self):
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
        return self.ns.connected

    async def clear_queue(self):
        self.stop()
        try:
            async with asyncio.timeout(30):
                while self.ns.stop:
                    await asyncio.sleep(1)
        except TimeoutError:
            return False
        self.unpause()
        return True
