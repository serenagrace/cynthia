"""Detect scenes and text in captured video frames."""

import asyncio
import logging
import re
import time
import unicodedata
from contextlib import closing
from datetime import datetime
from multiprocessing import shared_memory
from pathlib import Path

import cv2
import discord
import numpy
from paddleocr import PaddleOCR
from rapidfuzz import fuzz, process
from skimage.metrics import structural_similarity as ssim

from cynthia.utils.encounters import encounter_log_name

from .daemon import Daemon
from .dman import FB0
from .uvc import UVC

logging.getLogger("pytesseract").setLevel(logging.INFO)
logging.getLogger("ppocr").setLevel(logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
ocr = PaddleOCR(
    lang="en",
    use_textline_orientation=True,
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
)
SCENES_DIR = Path(__file__).resolve().parent / "scenes"
GAME_TITLES = {
    "pokemon home": "Pokémon HOME",
    "pokemon let s go pikachu": "Pokémon: Let's Go, Pikachu!",
    "pokemon let s go eevee": "Pokémon: Let's Go, Eevee!",
    "pokemon legends arceus": "Pokémon Legends: Arceus",
    "pokemon legends z a": "Pokémon Legends: Z-A",
    "pokemon scarlet": "Pokémon Scarlet",
    "pokemon violet": "Pokémon Violet",
    "pokemon sword": "Pokémon Sword",
    "pokemon shield": "Pokémon Shield",
    "pokemon brilliant diamond": "Pokémon Brilliant Diamond",
    "pokemon shining pearl": "Pokémon Shining Pearl",
}


def normalize_game_title(game):
    """Normalize accents and punctuation for matching OCR game titles."""
    normalized = unicodedata.normalize("NFKD", game.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", normalized).strip()


def canonical_game_title(game):
    """Correct a recognized game title while preserving unknown OCR text."""
    normalized = normalize_game_title(game)
    match = process.extractOne(
        normalized,
        GAME_TITLES.keys(),
        scorer=fuzz.ratio,
        score_cutoff=85,
    )
    return GAME_TITLES[match[0]] if match else game


class Scene:
    """Describe a reference image and its comparison region."""

    def __init__(
        self, buffer, *_, x=0, y=0, w=1920, h=1080, text=None, grayscale=False
    ):
        """Store a reference frame and its crop and comparison settings."""
        self.buffer = buffer
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.text = text
        self.grayscale = grayscale

    def ssim_match(self, buffer):
        """Return structural similarity between the reference and a frame crop."""
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
    """Analyze captured frames and publish game and encounter state."""

    def __init__(self, dman):
        """Create shared state and start the computer-vision worker."""

        def loop(ns, uns, fba, fbb, drive):
            """Read shared frames and process them until shutdown."""
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
                    """Classify scenes, detect encounters, and publish each frame."""

                    def encounter_timer(uns_time, timer, game):
                        """Log elapsed encounter time and flag long encounters."""
                        encounter_time = (uns_time - timer) / 1_000_000
                        with drive.open(ns.encounter_log, "a") as f:
                            f.write(f"{datetime.now()},{game},{encounter_time:0f}\n")
                        logger.info(f"Encounter Time: {encounter_time:.0f}ms")
                        uns.last_encounter_time = time.time()

                        if encounter_time > 2000:
                            return True

                        return False

                    timer = -1
                    timing_encounter = False
                    while ns.run:
                        while uns.fbptr is None:
                            await asyncio.sleep(0.05)
                        fbptr = uns.fbptr
                        uns_time = uns.uvc_time1 if fbptr else uns.uvc_time0
                        if ns.uvc_time != uns_time:
                            ns.uvc_time = uns_time
                            frame[:] = fb[fbptr][:]
                            perf_time = time.perf_counter()
                            # Only compared while a HOME tap is being checked
                            if uns.quick_settings_watch:
                                uns.quick_settings_open = (
                                    CV.quick_settings_scene.ssim_match(frame)
                                    > CV.QUICK_SETTINGS_THRESHOLD
                                )
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
                            scores["bdsp_run"] = CV.bdsp_run_scene.ssim_match(frame)
                            scores["route_202"] = CV.route_202_scene.ssim_match(frame)
                            scores["roamer"] = CV.bdsp_roamer_scene.ssim_match(frame)
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
                            uns.ssim_scores = sorted_scores[:5]
                            score_text = [
                                f"{key}: {value}" for key, value in sorted_scores
                            ]
                            if sorted_scores[0][1] > 0.9:
                                score_text[0] = f"**{score_text[0]}**"
                            embed.add_field(name="Scenes:", value="\n".join(score_text))

                            if uns.match_scene_id is not None:
                                if uns.match_scene_id in scores:
                                    if scores[uns.match_scene_id] > 0.98:
                                        uns.scene_matched = True

                            if sorted_scores[0][1] > 0.9:
                                if sorted_scores[0][0] in ("home", "afk_home"):
                                    game = CV.scrape_text(frame, y=200, h=100).strip()
                                    no_start_chars = ("-", ".", "_", ":", ";")
                                    while any(
                                        game.startswith(char) for char in no_start_chars
                                    ):
                                        game = game[1:].strip()
                                    game = re.sub(r"^[a-zA-Z\-] ", "", game)
                                    game = canonical_game_title(game)
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
                                    if ns.self_encounter:
                                        if "Go" in raw_text:
                                            timer = uns_time
                                            timing_encounter = True
                                        else:
                                            if timing_encounter:
                                                self.uns.nxbt_daemon_stop = (
                                                    encounter_timer(
                                                        uns_time, timer, ns.game
                                                    )
                                                )
                                                timing_encounter = False
                                    elif any(
                                        word in raw_text
                                        for word in ("appeared", "encountered")
                                    ):
                                        timer = uns_time
                                        timing_encounter = True
                                    else:  # not currently starting the timer
                                        if timing_encounter and not ns.self_encounter:
                                            self.uns.nxbt_daemon_stop = encounter_timer(
                                                uns_time, timer, ns.game
                                            )
                                            timing_encounter = False

                                if sorted_scores[0][0] in ("bdsp_run"):
                                    if (
                                        timing_encounter
                                    ):  # if this is a non-self it's too late anyways
                                        self.uns.nxbt_daemon_stop = encounter_timer(
                                            uns_time, timer, ns.game
                                        )
                                        timing_encounter = False
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
        self.uns.quick_settings_watch = False
        self.uns.quick_settings_open = False
        self.uns.match_scene_id = None
        self.uns.scene_matched = False
        self.uns.ssim_scores = []
        self.ns.png = None
        self.ns.home = False
        self.ns.game = None
        self.ns.embed = None
        self.ns.playing = False
        self.ns.self_encounter = False
        self.ns.encounter_log = encounter_log_name(dman.context.args.hunt)
        self.uns.encounter_log = self.ns.encounter_log
        self.loop = loop
        self.start()

    def set_hunt(self, hunt):
        """Update the encounter log path for the active hunt."""
        self.ns.encounter_log = encounter_log_name(hunt)
        self.uns.encounter_log = self.ns.encounter_log

    def set_self_encounter(self, *, self_encounter=True):
        """Set whether encounter detection uses the self-encounter flow."""
        self.ns.self_encounter = self_encounter


class CV:
    """OCR helpers and reference scenes used by the computer-vision daemon."""

    @staticmethod
    def _recognize(gray):
        """Run OCR on a grayscale image and return the recognized lines."""
        if not hasattr(ocr, "predict"):
            # PaddleOCR 2.x is still installed; `pip install -e .` upgrades it
            result = ocr.ocr(gray, cls=True)
            return "\n".join(line[1][0] for page in result for line in page or [])
        result = ocr.predict(cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR))
        return "\n".join(text for page in result for text in page["rec_texts"])

    @staticmethod
    def scrape_text(buffer, *_, x=0, y=0, w=1920, h=1080):
        """Extract text from a frame crop, retrying OCR with inverted colors."""
        cropped = buffer[y : y + h][x : x + w]
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        text = CV._recognize(gray)
        if not text or text.isspace():
            text = CV._recognize(cv2.bitwise_not(gray))
        return text

    # Opaque "Sleep Mode" button of the quick settings menu; the rest of the menu
    # is translucent and varies with whatever is behind it.
    QUICK_SETTINGS_THRESHOLD = 0.95
    quick_settings_scene = Scene(
        cv2.imread(str(SCENES_DIR / "quick_settings_sleep.png")),
        x=1222,
        y=180,
        w=640,
        h=120,
        grayscale=True,
    )
    home_screen_scene = Scene(
        cv2.imread(str(SCENES_DIR / "switch_home_screen.png")),
        y=720,
        h=200,
    )
    afk_home_screen_scene = Scene(
        cv2.imread(str(SCENES_DIR / "switch_home_screen_afk.png")),
        y=720,
        h=200,
    )
    boot_screen_scene = Scene(
        cv2.imread(str(SCENES_DIR / "switch_boot_screen.png")),
        x=1580,
        y=920,
    )
    elgato_no_signal_scene = Scene(cv2.imread(str(SCENES_DIR / "elgato_no_signal.png")))
    bdsp_tbox_scene = Scene(
        cv2.imread(str(SCENES_DIR / "bdsp_tbox.png")),
        x=90,
        y=873,
        w=50,
        h=180,
    )
    bdsp_run_scene = Scene(
        cv2.imread(str(SCENES_DIR / "bdsp_run.png")),
        x=1550,
        y=970,
        w=330,
        h=80,
    )
    bdsp_roamer_scene = Scene(
        cv2.imread(str(SCENES_DIR / "roamer.png")),
        x=1435,
        y=214,
        w=124,
        h=97,
    )
    route_202_scene = Scene(
        cv2.imread(str(SCENES_DIR / "bdsp_route_202.png")),
        x=1475,
        y=222,
        w=70,
        h=60,
    )
