import asyncio
from contextlib import closing
import cv2
from multiprocessing import shared_memory
import io
import numpy
import subprocess
import time
import logging
import xxhash
from .daemon import Daemon
from .dman import FB0

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# From `lsusb`
ELGATO_USB_ID = "0fd9:009b"


class UVCDaemon(Daemon):
    def __init__(self, dman):
        def loop(ns, uns, fba, fbb):
            with (
                closing(shared_memory.SharedMemory(name=fba)) as shmA,
                closing(shared_memory.SharedMemory(name=fbb)) as shmB,
            ):
                shm = (shmA, shmB)
                fb = list(
                    numpy.ndarray(FB0.shape(), dtype=numpy.uint8, buffer=shm[idx].buf)
                    for idx in (0, 1)
                )

                async def main_task():
                    uvc = UVC()
                    await uvc.setup()

                    while ns.run:
                        if uvc.cap is None:
                            uvc.setup()
                        frame = await uvc.read_frame()
                        _time = time.time_ns()
                        _hash = xxhash.xxh3_64_intdigest(frame.data)
                        fbptr = 1 if uns.fbptr == 0 else 0

                        if fbptr:
                            uns.uvc_hash1, uns.uvc_time1 = _hash, _time
                        else:
                            uns.uvc_hash0, uns.uvc_time0 = _hash, _time
                        fb[fbptr][:] = frame

                        uns.fbptr = fbptr

                asyncio.run(main_task())

        super().__init__(dman, fbs=(0,))
        self.uns.uvc_hash0 = None
        self.uns.uvc_time0 = None
        self.uns.uvc_hash1 = None
        self.uns.uvc_time1 = None
        self.loop = loop
        self.start()


class UVC:
    def __init__(self):
        self.cap = None

    async def setup(self):
        subprocess.run(["usbreset", ELGATO_USB_ID])

        await asyncio.sleep(2)  # Wait for the device to reset

        self.cap = cv2.VideoCapture(-1)

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        self.cap.set(cv2.CAP_PROP_FPS, 30)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        await asyncio.sleep(1)  # Give the camera some time to initialize

        await self.read_frame()

    async def read_frame(self):
        if self.cap is None:
            await self.setup()
        ret = False
        frame = None
        good_img = False

        try:
            async with asyncio.timeout(5):
                logger.debug("Attempting to read frame from UVC device.")
                while not good_img:
                    self.cap.grab()  # Grab the latest frame to clear the buffer

                    ret, frame = self.cap.read()
                    if ret:
                        good_img = (
                            cv2.countNonZero(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
                            > 0
                        )
                    logger.debug(f"Good Image: {bool(good_img)}")
                    await asyncio.sleep(0.05)  # Avoid busy waiting
        except TimeoutError:
            pass

        if not ret:
            logger.error("Failed to read frame from UVC device.")
            return None
        frame = cv2.flip(frame, 0)
        return frame

    @staticmethod
    def frame_to_buffer(frame):
        success, buffer = cv2.imencode(".png", frame)
        if not success:
            logger.error("Failed to encode frame as PNG.")
            return None
        io_buf = io.BytesIO(buffer)
        io_buf.seek(0)
        return io_buf

    def release(self):
        if self.cap is not None:
            self.cap.release()
