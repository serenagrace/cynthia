import asyncio
import re
import time
import cv2
from skimage.metrics import structural_similarity as ssim
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


class Scene:
    def __init__(
        self, buffer, *_, x=0, y=0, w=1920, h=1080, text=None, grayscale=False
    ):
        self.buffer = buffer
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.text = text
        self.grayscale = grayscale

    def ssim_match(self, buffer):
        cropped = buffer[self.y : self.y + self.h, self.x : self.x + self.w]

        if self.grayscale:
            score = ssim(
                cv2.cvtColor(self.buffer, cv2.COLOR_BGR2GRAY),
                cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY),
            )
        else:
            score = ssim(
                cv2.resize(self.buffer, (0, 0), fx=0.5, fy=0.5),
                cv2.resize(cropped, (0, 0), fx=0.5, fy=0.5),
                channel_axis=-1,
            )
        return score


class UVCDaemon(Daemon):
    home_screen_scene = Scene(
        cv2.imread("/raidarchive/cynthia_drive/scenes/switch_home_screen.png"),
        y=720,
        h=200,
    )
    afk_home_screen_scene = Scene(
        cv2.imread("/raidarchive/cynthia_drive/scenes/switch_home_screen_afk.png"),
        y=720,
        h=200,
    )
    boot_screen_scene = Scene(
        cv2.imread("/raidarchive/cynthia_drive/scenes/switch_boot_screen.png"),
        x=1580,
        y=920,
    )
    elgato_no_signal_scene = Scene(
        cv2.imread("/raidarchive/cynthia_drive/scenes/elgato_no_signal.png")
    )

    def __init__(self):

        def loop(run, ns):
            async def main_task():
                uvc = UVC()
                await uvc.setup()

                while run:
                    if uvc.cap is None:
                        uvc.setup()
                    scores = {}
                    perf_times = [time.perf_counter()]
                    frame = await uvc.read_frame()
                    perf_times.append(time.perf_counter())
                    raw_text = uvc.scrape_text(frame)
                    perf_times.append(time.perf_counter())
                    scores["home"] = UVCDaemon.home_screen_scene.ssim_match(frame)
                    scores["afk_home"] = UVCDaemon.afk_home_screen_scene.ssim_match(
                        frame
                    )
                    scores["boot"] = UVCDaemon.boot_screen_scene.ssim_match(frame)
                    scores["elgato_no_signal"] = (
                        UVCDaemon.elgato_no_signal_scene.ssim_match(frame)
                    )
                    perf_times.append(time.perf_counter())
                    buffer = uvc.frame_to_buffer(frame)
                    perf_times.append(time.perf_counter())
                    filename = f"frame.png"

                    embed = discord.Embed(title="UVC Data:")
                    embed.set_image(url=f"attachment://{filename}")
                    sorted_scores = list(
                        sorted(scores.items(), key=lambda item: item[1], reverse=True)
                    )
                    score_text = [f"{key}: {value}" for key, value in sorted_scores]
                    score_text[0] = f"**{score_text[0]}**"
                    embed.add_field(name="Scenes:", value="\n".join(score_text))

                    if sorted_scores[0][1] > 0.9:
                        if sorted_scores[0][0] in ("home", "afk_home"):
                            game = uvc.scrape_text(frame, y=200, h=100)
                            game = re.sub(r"^[a-zA-Z] ", "", game)
                            embed.add_field(name="Selected Game:", value=game)
                            ns.game = game
                            ns.home = True
                            ns.playing = False
                        if sorted_scores[0][0] in ("elgato_no_signal"):
                            ns.home = False
                            ns.playing = False
                        if sorted_scores[0][0] in ("boot", "boot2"):
                            ns.home = False
                            ns.playing = True
                    elif not raw_text.isspace():
                        embed.add_field(name="Detected Text:", value=raw_text)
                        ns.home = False
                        ns.playing = True
                    else:
                        ns.home = False
                        ns.playing = True
                    embed.set_footer(
                        text=f"Frame: {(perf_times[1]-perf_times[0])*1000:.0f}ms, Text: {(perf_times[2]-perf_times[1])*1000:.0f}ms, Scene: {(perf_times[3]-perf_times[2])*1000:.0f}ms"
                    )
                    ns.embed, ns.png = embed, buffer.getvalue()

            asyncio.run(main_task())

        self.loop = loop
        super().__init__()
        self.ns.game = None
        self.ns.playing = False
        self.ns.home = False


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

    def scrape_text(self, buffer, *_, x=0, y=0, w=1920, h=1080):
        cropped = buffer[y : y + h][x : x + w]
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        text = pytesseract.image_to_string(gray)
        return text

    def release(self):
        if self.cap is not None:
            self.cap.release()
