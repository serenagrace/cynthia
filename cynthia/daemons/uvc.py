import asyncio
import time
import cv2
import pytesseract
import io
import subprocess
import logging
import discord
from .daemon import Daemon

logging.getLogger("pytesseract").setLevel(logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# From `lsusb`
ELGATO_USB_ID = "0fd9:009b"


class UVCDaemon(Daemon):
    def __init__(self):
        def loop(run, ns):
            async def main_task():
                uvc = UVC()
                await uvc.setup()

                while run:
                    if uvc.cap is None:
                        uvc.setup()
                    perf_times = [time.perf_counter()]
                    frame = await uvc.read_frame()
                    perf_times.append(time.perf_counter())
                    text = uvc.scrape_text(frame)
                    perf_times.append(time.perf_counter())
                    buffer = uvc.frame_to_buffer(frame)
                    perf_times.append(time.perf_counter())
                    filename = f"frame.png"

                    embed = discord.Embed(title="UVC Data:")
                    embed.set_image(url=f"attachment://{filename}")

                    if not text.isspace():
                        embed.add_field(name="Detected Text:", value=text)
                    embed.set_footer(
                        text=f"Frame: {(perf_times[1]-perf_times[0])*1000:.0f}ms, Text: {(perf_times[2]-perf_times[1])*1000:.0f}ms"
                    )
                    ns.embed, ns.png = embed, buffer.getvalue()

            asyncio.run(main_task())

        self.loop = loop
        super().__init__()


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

    async def get_cv_embed(self):
        if self.cap is None:
            await self.setup()
        perf_times = [time.perf_counter()]
        frame = await self.read_frame()
        perf_times.append(time.perf_counter())
        text = self.scrape_text(frame)
        perf_times.append(time.perf_counter())
        buffer = self.frame_to_buffer(frame)
        perf_times.append(time.perf_counter())
        filename = f"frame{time.time_ns() // 1_000_000}.png"
        png = discord.File(fp=buffer, filename=filename)

        embed = discord.Embed(title="UVC Data:")
        embed.set_image(url=f"attachment://{filename}")

        if not text.isspace():
            embed.add_field(name="Detected Text:", value=text)
        embed.set_footer(
            text=f"Frame: {(perf_times[1]-perf_times[0])*1000:.0f}ms, Text: {(perf_times[2]-perf_times[1])*1000:.0f}ms"
        )

        return embed, buffer.getvalue()

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

    def frame_to_buffer(self, frame):
        success, buffer = cv2.imencode(".png", frame)
        if not success:
            logger.error("Failed to encode frame as PNG.")
            return None
        io_buf = io.BytesIO(buffer)
        io_buf.seek(0)
        return io_buf

    def scrape_text(self, buffer):
        gray = cv2.cvtColor(buffer, cv2.COLOR_BGR2GRAY)
        text = pytesseract.image_to_string(gray)
        return text

    def release(self):
        if self.cap is not None:
            self.cap.release()
