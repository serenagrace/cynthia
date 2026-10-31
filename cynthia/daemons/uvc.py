"""Capture video frames from the configured USB video device."""

import asyncio
import io
import logging
import subprocess
import time
from contextlib import closing
from multiprocessing import shared_memory

import cv2
import numpy
import xxhash

from .daemon import Daemon
from .dman import FB0

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class UVCDaemon(Daemon):
    """Read UVC frames into alternating shared-memory buffers."""

    def __init__(self, dman):
        """Initialize shared frame metadata and start the capture process."""

        def loop(ns, uns, fba, fbb, usb_id):
            """Capture frames and publish them through shared memory."""
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
                    """Read frames and update the active shared buffer metadata."""
                    uvc = UVC(usb_id)
                    await uvc.setup()

                    while ns.run:
                        if uvc.cap is None:
                            await uvc.setup()
                        frame = await uvc.read_frame()
                        if frame is None:
                            # Capture dropped out; reopen (and USB reset) it
                            uvc.release()
                            uvc.cap = None
                            await asyncio.sleep(1)
                            continue
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

        super().__init__(
            dman, dman.context.env.get("ELGATO_USB_ID", None) or None, fbs=(0,)
        )
        self.uns.uvc_hash0 = None
        self.uns.uvc_time0 = None
        self.uns.uvc_hash1 = None
        self.uns.uvc_time1 = None
        self.loop = loop
        self.start()


class UVC:
    """Open and read frames from a USB video capture device."""

    def __init__(self, usb_id=None):
        """Store the capture card's `vendor:product` USB ID, if one is configured."""
        self.usb_id = usb_id
        self.cap = None

    async def setup(self):
        """Reset the USB device (when its ID is configured) and open the capture."""
        if self.usb_id:
            subprocess.run(["usbreset", self.usb_id])
            await asyncio.sleep(2)  # Wait for the device to reset
        else:
            logger.warning("ELGATO_USB_ID is not set; skipping the USB reset.")

        self.cap = cv2.VideoCapture(-1)

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        self.cap.set(cv2.CAP_PROP_FPS, 60)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        await asyncio.sleep(1)  # Give the camera some time to initialize

        await self.read_frame()

    async def read_frame(self):
        """Read and vertically flip a frame, or return None on timeout."""
        if self.cap is None:
            await self.setup()
        ret = False
        frame = None
        good_img = False

        try:
            async with asyncio.timeout(5):
                logger.debug("Attempting to read frame from UVC device.")
                ret, frame = self.cap.read()
                while not ret:
                    await asyncio.sleep(0.05)  # Avoid busy waiting
                    ret, frame = self.cap.read()
        except TimeoutError:
            pass

        if not ret:
            logger.error("Failed to read frame from UVC device.")
            return None
        frame = cv2.flip(frame, 0)
        return frame

    @staticmethod
    def frame_to_buffer(frame):
        """Encode a frame as PNG and return it in a rewound byte buffer."""
        success, buffer = cv2.imencode(".png", frame)
        if not success:
            logger.error("Failed to encode frame as PNG.")
            return None
        io_buf = io.BytesIO(buffer)
        io_buf.seek(0)
        return io_buf

    def release(self):
        """Release the active video capture, if one exists."""
        if self.cap is not None:
            self.cap.release()
