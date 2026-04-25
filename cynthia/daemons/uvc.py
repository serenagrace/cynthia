import asyncio
import cv2
import io
import subprocess
import logging
import discord
from .daemon import Daemon

logger = logging.getLogger(__name__)

# From `lsusb`
ELGATO_USB_ID = "0fd9:009b"


class UVC(Daemon):
    def __init__(self):
        self.cap = None

    async def setup(self):
        subprocess.run(["usbreset", ELGATO_USB_ID])

        await asyncio.sleep(2)  # Wait for the device to reset

        self.cap = cv2.VideoCapture(-1)

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1200)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        self.cap.set(cv2.CAP_PROP_FPS, 30)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        await asyncio.sleep(1)  # Give the camera some time to initialize

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
                    await asyncio.sleep(0.1)  # Avoid busy waiting
        except TimeoutError:
            pass

        if not ret:
            logger.error("Failed to read frame from UVC device.")
            return None
        frame = cv2.flip(frame, 0)
        success, buffer = cv2.imencode(".png", frame)
        if not success:
            logger.error("Failed to encode frame as PNG.")
            return None
        io_buf = io.BytesIO(buffer)
        io_buf.seek(0)
        with open("frame.png", "wb") as f:
            f.write(io_buf.read())
        io_buf.seek(0)
        png = discord.File(fp=io_buf, filename="frame.png")
        return png

    def release(self):
        if self.cap is not None:
            self.cap.release()
