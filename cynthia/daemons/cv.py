import asyncio
from contextlib import closing
from datetime import datetime
import re
import time
import cv2
from skimage.metrics import structural_similarity as ssim
from paddleocr import PaddleOCR
import numpy
from multiprocessing import shared_memory
import logging
import discord
from .daemon import Daemon
from .dman import FB0
from .uvc import UVC

logging.getLogger("pytesseract").setLevel(logging.INFO)
logging.getLogger("ppocr").setLevel(logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
ocr = PaddleOCR(use_angle_cls=True, lang="en")


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
        x, y, w, h = self.x, self.y, self.w, self.h
        cropped = buffer[y : y + h, x : x + w]
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


class CVDaemon(Daemon):
    def __init__(self, dman):
        def loop(ns, uns, fba, fbb, drive):
            with (
                closing(shared_memory.SharedMemory(name=fba)) as shmA,
                closing(shared_memory.SharedMemory(name=fbb)) as shmB,
            ):
                shm = (shmA, shmB)
                fb = list(
                    numpy.ndarray(FB0.shape(), dtype=numpy.uint8, buffer=shm[idx].buf)
                    for idx in (0, 1)
                )
                frame = numpy.zeros(FB0.shape(), dtype=numpy.uint8)

                async def main_task():
                    timer = -1
                    timer_string = None
                    while ns.run:
                        while uns.fbptr is None:
                            await asyncio.sleep(0.05)
                        fbptr = uns.fbptr
                        uns_time = uns.uvc_time1 if fbptr else uns.uvc_time0
                        if ns.uvc_time != uns_time:
                            ns.uvc_time = uns_time
                            frame[:] = fb[fbptr][:]
                            perf_time = time.perf_counter()
                            scores = {}
                            scores["home"] = CV.home_screen_scene.ssim_match(frame)
                            scores["afk_home"] = CV.afk_home_screen_scene.ssim_match(
                                frame
                            )
                            scores["boot"] = CV.boot_screen_scene.ssim_match(frame)
                            scores["elgato_no_signal"] = (
                                CV.elgato_no_signal_scene.ssim_match(frame)
                            )
                            scores["bdsp_tbox"] = CV.bdsp_tbox_scene.ssim_match(frame)
                            buffer = UVC.frame_to_buffer(frame)
                            filename = "frame.png"

                            embed = discord.Embed(title="UVC Data:")
                            embed.set_image(url=f"attachment://{filename}")
                            sorted_scores = list(
                                sorted(
                                    scores.items(),
                                    key=lambda item: item[1],
                                    reverse=True,
                                )
                            )
                            score_text = [
                                f"{key}: {value}" for key, value in sorted_scores
                            ]
                            if sorted_scores[0][1] > 0.9:
                                score_text[0] = f"**{score_text[0]}**"
                            embed.add_field(name="Scenes:", value="\n".join(score_text))

                            if sorted_scores[0][1] > 0.9:
                                if sorted_scores[0][0] in ("home", "afk_home"):
                                    game = CV.scrape_text(frame, y=200, h=100).strip()
                                    if game.startswith("-"):
                                        game = game.replace("-", "").strip()
                                    game = re.sub(r"^[a-zA-Z\-] ", "", game)
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
                                if sorted_scores[0][0] in ("bdsp_tbox"):
                                    raw_text = CV.scrape_text(
                                        frame, y=870, h=260, w=860
                                    )
                                    if "appeared" in raw_text:
                                        timer = uns_time
                                        timer_string = "appeared"
                                    else:
                                        if timer_string == "appeared":
                                            encounter_time = (
                                                uns_time - timer
                                            ) / 1_000_000
                                            with drive.open(
                                                "encounter_times.log", "a"
                                            ) as f:
                                                f.write(
                                                    f"{datetime.now()},{ns.game},{encounter_time:0f}\n"
                                                )
                                            print(
                                                f"Encounter Time: {encounter_time:.0f}ms"
                                            )

                                            if encounter_time > 2000:
                                                self.uns.nxbt_daemon_stop = True

                                            timer_string = None
                            # elif not raw_text.isspace():
                            #    embed.add_field(name="Detected Text:", value=raw_text)
                            #    ns.home = False
                            #    ns.playing = True
                            else:
                                ns.home = False
                                ns.playing = True
                            embed.set_footer(
                                text=f"Scene: {(time.perf_counter() - perf_time)*1000:.0f}ms"
                            )
                            ns.embed, ns.png = embed, buffer.getvalue()

                asyncio.run(main_task())

        super().__init__(dman, dman.drive, fbs=(0,))
        self.ns.uvc_time = -1
        self.uns.nxbt_daemon_stop = False
        self.ns.png = None
        self.ns.home = False
        self.ns.game = None
        self.ns.embed = None
        self.ns.playing = False
        self.loop = loop
        self.start()


class CV:
    @staticmethod
    def scrape_text(buffer, *_, x=0, y=0, w=1920, h=1080):
        cropped = buffer[y : y + h][x : x + w]
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        result = ocr.ocr(gray, cls=True)
        text = ""
        if hasattr(next(iter(result[0:1]), None), "__iter__"):
            text = "\n".join([line[1][0] for line in result[0]])
        if not text or text.isspace():
            gray = cv2.bitwise_not(gray)
            result = ocr.ocr(gray, cls=True)
            if hasattr(next(iter(result[0:1]), None), "__iter__"):
                text = "\n".join([line[1][0] for line in result[0]])
        return text

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
    bdsp_boot_scene = Scene(
        cv2.imread("/raidarchive/cynthia_drive/scenes/bdsp_boot.png")
    )
    bdsp_tbox_scene = Scene(
        cv2.imread("/raidarchive/cynthia_drive/scenes/bdsp_tbox.png"),
        x=90,
        y=873,
        w=50,
        h=180,
    )
