"""Detect scenes and text in captured video frames."""

import asyncio
import logging
import os
import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import cv2
import discord
import numpy

from cynthia.utils.log import get_logger, quiet_ocr

quiet_ocr()

from rapidfuzz import fuzz, process
from skimage.metrics import structural_similarity as ssim

from cynthia.utils.encounters import encounter_log_name
from cynthia.utils.streamcfg import CV_FPS

from .daemon import Daemon
from .dman import FB0
from .uvc import UVC

logger = get_logger(__name__, logging.INFO)
SCENE_SCALE = 0.5  # scenes are compared on a half-size frame
THUMB_SIZE = (32, 18)  # thumbnail used to rule out hopeless matches
SSIM_WINDOW = 7  # skimage's default window, kept so scores stay comparable
PREVIEW_INTERVAL = 1.0  # seconds between PNG/embed refreshes for the bot
# CV yields CPU to NXBT, which needs the highest priority for Bluetooth
CV_NICE = 10
CV_THREADS = 2


def build_ocr():
    """Create the OCR engine on the GPU, falling back to the CPU."""
    # Paddle is imported here, not at module level: importing it in the parent
    # breaks CUDA in every daemon forked afterwards.
    import paddle
    from paddleocr import PaddleOCR

    # Paddle prints a C++ traceback when the daemon is SIGTERMed on shutdown
    paddle.disable_signal_handler()
    quiet_ocr()  # paddlex resets its own logger level on import
    options = dict(
        lang="en",
        use_textline_orientation=True,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
    )
    if paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count():
        try:
            return PaddleOCR(device="gpu:0", **options)
        except Exception as error:
            logger.warning("GPU OCR unavailable; falling back to the CPU: %s", error)
    return PaddleOCR(**options)


# Built on first use, inside the process that runs OCR.
ocr = None


def get_ocr():
    """Return the shared OCR engine, creating it on first use."""
    global ocr
    if ocr is None:
        ocr = build_ocr()
    return ocr


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
    "pokemon firered version": "Pokémon FireRed Version",
    "pokemon fire red version": "Pokémon FireRed Version",
    "pokemon firered": "Pokémon FireRed Version",
    "pokemon fire red": "Pokémon FireRed Version",
    "pokemon leafgreen version": "Pokémon LeafGreen Version",
    "pokemon leaf green version": "Pokémon LeafGreen Version",
    "pokemon leafgreen": "Pokémon LeafGreen Version",
    "pokemon leaf green": "Pokémon LeafGreen Version",
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


def _window_stats(image):
    """Return the windowed mean and sample variance SSIM needs for one image."""
    mean = cv2.blur(image, (SSIM_WINDOW, SSIM_WINDOW))
    squares = cv2.blur(image * image, (SSIM_WINDOW, SSIM_WINDOW))
    area = SSIM_WINDOW * SSIM_WINDOW
    return mean, (squares - mean * mean) * (area / (area - 1))


def fast_ssim(ref, ref_stats, image):
    """Mean structural similarity of two same-size uint8 images.

    Matches `skimage.metrics.structural_similarity` (uniform window, sample
    covariance) but works in float32 with OpenCV box filters, and takes the
    reference's window statistics precomputed since the reference never changes.
    """
    pad = (SSIM_WINDOW - 1) // 2
    if min(ref.shape[:2]) <= SSIM_WINDOW:
        return ssim(ref, image, channel_axis=-1 if ref.ndim == 3 else None)
    other = image.astype(numpy.float32)
    ref_mean, ref_var = ref_stats
    mean, var = _window_stats(other)
    area = SSIM_WINDOW * SSIM_WINDOW
    # Use sample covariance, matching skimage's normalization for the same window.
    cov = (cv2.blur(ref.astype(numpy.float32) * other, (SSIM_WINDOW,) * 2)) - (
        ref_mean * mean
    )
    cov *= area / (area - 1)
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    score = ((2 * ref_mean * mean + c1) * (2 * cov + c2)) / (
        (ref_mean * ref_mean + mean * mean + c1) * (ref_var + var + c2)
    )
    return float(score[pad:-pad, pad:-pad].mean())


def _score_scenes(frame, uns_time, *, check_quick_settings=False):
    """Compare the frame with reference scenes, optionally checking the HOME menu."""
    scores = {}
    quick_settings_open = None

    small = cv2.resize(
        frame,
        (0, 0),
        fx=SCENE_SCALE,
        fy=SCENE_SCALE,
        interpolation=cv2.INTER_AREA,
    )

    if check_quick_settings:
        quick_settings_open = (
            CV.quick_settings_scene.ssim_match(small, SCENE_SCALE, frame, uns_time)
            > CV.QUICK_SETTINGS_THRESHOLD
        )

    scores["home"] = CV.home_screen_scene.ssim_match(
        small, SCENE_SCALE, frame, uns_time
    )
    scores["afk_home"] = CV.afk_home_screen_scene.ssim_match(
        small, SCENE_SCALE, frame, uns_time
    )
    scores["boot"] = CV.boot_screen_scene.ssim_match(
        small, SCENE_SCALE, frame, uns_time
    )
    scores["elgato_no_signal"] = CV.elgato_no_signal_scene.ssim_match(
        small, SCENE_SCALE, frame, uns_time
    )
    scores["bdsp_tbox"] = CV.bdsp_tbox_scene.ssim_match(
        small, SCENE_SCALE, frame, uns_time
    )
    scores["bdsp_run"] = CV.bdsp_run_scene.ssim_match(
        small, SCENE_SCALE, frame, uns_time
    )
    scores["route_202"] = CV.route_202_scene.ssim_match(
        small, SCENE_SCALE, frame, uns_time
    )
    scores["roamer"] = CV.bdsp_roamer_scene.ssim_match(
        small, SCENE_SCALE, frame, uns_time
    )
    scores["bdsp_bag"] = CV.bdsp_bag_scene.ssim_match(
        small, SCENE_SCALE, frame, uns_time
    )

    return scores, quick_settings_open


class Scene:
    """Describe a reference image and its comparison region.

    `scale` is the frame scale the scene is compared at (default `SCENE_SCALE`);
    large, slowly changing scenes use a smaller one. `interval` is the minimum
    seconds between comparisons, with the last score reused in between.
    `reject` is a mean-difference limit on a thumbnail above which the frame
    cannot be a match, so the full comparison is skipped and 0.0 returned.
    """

    def __init__(
        self,
        buffer,
        *_,
        x=0,
        y=0,
        w=1920,
        h=1080,
        text=None,
        grayscale=False,
        scale=None,
        interval=0.0,
        reject=None,
    ):
        """Store a reference frame and its crop and comparison settings."""
        self.buffer = buffer
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.text = text
        self.grayscale = grayscale
        self.scale = SCENE_SCALE if scale is None else scale
        self.interval_ns = int(interval * 1e9)
        self.reject = reject

    def _scaled(self, scale):
        """Return the cached crop box, reference, and its SSIM statistics."""
        cache = self.__dict__.setdefault("_scaled_cache", {})
        if scale not in cache:
            if scale == 1.0:
                ref, box = self.buffer, (self.x, self.y, self.w, self.h)
            else:
                ref = cv2.resize(
                    self.buffer,
                    (0, 0),
                    fx=scale,
                    fy=scale,
                    interpolation=cv2.INTER_AREA,
                )
                h, w = ref.shape[:2]
                box = (round(self.x * scale), round(self.y * scale), w, h)
            if self.grayscale:
                ref = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)
            ref_f = ref.astype(numpy.float32)
            thumb = cv2.resize(ref, THUMB_SIZE, interpolation=cv2.INTER_AREA)
            cache[scale] = (box, ref_f, _window_stats(ref_f), thumb.astype(numpy.int16))
        return cache[scale]

    def _aligned(self, scale):
        """Whether the crop lands on whole pixels of a frame scaled by `scale`."""
        return all(
            abs(value * scale - round(value * scale)) < 1e-6
            for value in (self.x, self.y, self.w, self.h)
        )

    def ssim_match(self, buffer, scale=1.0, full=None, now_ns=None):
        """Return structural similarity between the reference and a frame crop.

        `buffer` is the frame resized by `scale`; the crop and reference are scaled
        to match, so comparisons rarely touch full-resolution pixels. Crops that
        would straddle a scaled pixel are cut from the `full` frame and resized,
        which keeps their scores aligned with the reference. With `now_ns` and an
        `interval`, the previous score is reused until the interval has passed.
        """
        if self.interval_ns and now_ns is not None:
            last = self.__dict__.get("_last")
            if last and now_ns - last[0] < self.interval_ns:
                return last[1]
            score = self._match(buffer, scale, full)
            self._last = (now_ns, score)
            return score
        return self._match(buffer, scale, full)

    def _match(self, buffer, scale, full):
        """Compare one frame to the reference, without interval caching."""
        _, ref, stats, thumb = self._scaled(scale)
        if scale != 1.0 and full is not None and not self._aligned(scale):
            # Crop before resizing when fractional edges would shift the reference region.
            cropped = cv2.resize(
                full[self.y : self.y + self.h, self.x : self.x + self.w],
                (0, 0),
                fx=scale,
                fy=scale,
                interpolation=cv2.INTER_AREA,
            )
        else:
            (x, y, w, h), *_ = self._scaled(scale)
            cropped = buffer[y : y + h, x : x + w]
        if self.grayscale:
            cropped = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        if self.reject is not None:
            small = cv2.resize(cropped, THUMB_SIZE, interpolation=cv2.INTER_AREA)
            if numpy.abs(small.astype(numpy.int16) - thumb).mean() > self.reject:
                return 0.0
        return fast_ssim(ref, stats, cropped)


class CVDaemon(Daemon):
    """Analyze captured frames and publish game and encounter state."""

    PERSISTED_STATE = ("encounter_log", "self_encounter", "game", "home", "playing")

    def __init__(self, dman):
        """Create shared state and start the computer-vision worker."""

        def loop(ns, uns, ring, drive):
            """Read shared frames and process them until shutdown."""
            os.nice(CV_NICE)
            cv2.setNumThreads(CV_THREADS)
            get_ocr()  # load the models now rather than during a hunt
            frame = numpy.zeros(FB0.shape(), dtype=numpy.uint8)

            async def main_task():
                """Classify scenes, detect encounters, and publish each frame."""

                def encounter_timer(uns_time, timer, game):
                    """Log elapsed encounter time and flag long encounters."""
                    encounter_time = (uns_time - timer) / 1_000_000
                    with drive.open(ns.encounter_log, "a") as f:
                        f.write(f"{datetime.now()},{game},{encounter_time:0f}\n")
                    logger.notice(f"Encounter time: {encounter_time:.0f}ms")
                    uns.last_encounter_time = time.time()
                    uns.encounter_count = getattr(uns, "encounter_count", 0) + 1

                    if encounter_time > 2000:
                        return True

                    return False

                timer = -1
                timing_encounter = False
                last_seq = 0
                last_preview = 0.0
                last_cv_ns = 0

                def finish_encounter(uns_time):
                    """Complete a pending encounter and publish its shiny-stop signal."""
                    nonlocal timing_encounter
                    self.uns.nxbt_daemon_stop = encounter_timer(
                        uns_time, timer, ns.game
                    )
                    timing_encounter = False

                def update_scene(scene, frame, uns_time, embed):
                    """Apply the strongest scene's game and encounter transitions."""
                    nonlocal timer, timing_encounter
                    if scene in ("home", "afk_home"):
                        game = CV.scrape_text(frame, y=200, h=100).strip()
                        no_start_chars = ("-", ".", "_", ":", ";")
                        while any(game.startswith(char) for char in no_start_chars):
                            game = game[1:].strip()
                        game = re.sub(r"^[a-zA-Z\-] ", "", game)
                        game = canonical_game_title(game)
                        if game:
                            embed.add_field(name="Selected Game:", value=game)
                            ns.game = game
                        ns.home = True
                        ns.playing = False
                    if scene in ("elgato_no_signal"):
                        ns.home = False
                        ns.playing = False
                    if scene in ("boot", "boot2"):
                        ns.home = False
                        ns.playing = True
                    if scene in ("bdsp_tbox"):
                        raw_text = CV.scrape_text(frame, y=870, h=260, w=860)
                        if ns.self_encounter:
                            if "Go" in raw_text:
                                timer = uns_time
                                timing_encounter = True
                            elif timing_encounter:
                                finish_encounter(uns_time)
                        elif any(
                            word in raw_text for word in ("appeared", "encountered")
                        ):
                            timer = uns_time
                            timing_encounter = True
                        else:  # not currently starting the timer
                            if timing_encounter and not ns.self_encounter:
                                finish_encounter(uns_time)
                    if scene in ("bdsp_run"):
                        if (
                            timing_encounter
                        ):  # if this is a non-self it's too late anyways
                            finish_encounter(uns_time)

                def analyze_frame(frame, uns_time):
                    """Score scenes, update shared state, and build the preview embed."""
                    scores, quick_settings_open = _score_scenes(
                        frame,
                        uns_time,
                        check_quick_settings=uns.quick_settings_watch,
                    )
                    if quick_settings_open is not None:
                        uns.quick_settings_open = quick_settings_open
                    perf_time = time.perf_counter()
                    # Only compared while a HOME tap is being checked
                    filename = "frame.png"
                    embed = discord.Embed(title="UVC Data:")
                    embed.set_image(url=f"attachment://{filename}")
                    sorted_scores = sorted(
                        scores.items(), key=lambda item: item[1], reverse=True
                    )
                    uns.ssim_scores = sorted_scores[:5]
                    score_text = [f"{key}: {value}" for key, value in sorted_scores]
                    if sorted_scores[0][1] > 0.9:
                        score_text[0] = f"**{score_text[0]}**"
                    embed.add_field(name="Scenes:", value="\n".join(score_text))
                    # Read once: the macro process may clear it between proxy reads
                    match_scene_id = uns.match_scene_id
                    if scores.get(match_scene_id, 0) > 0.98:
                        uns.scene_matched = True
                    if sorted_scores[0][1] > 0.9:
                        update_scene(sorted_scores[0][0], frame, uns_time, embed)
                    else:
                        ns.home = False
                        ns.playing = True
                    embed.set_footer(
                        text=f"Scene: {(time.perf_counter() - perf_time)*1000:.0f}ms"
                    )
                    return embed

                async def publish_preview(embed):
                    """Refresh the PNG at the preview rate and mark frame processing live."""
                    nonlocal last_preview
                    if time.time() - last_preview >= PREVIEW_INTERVAL:
                        last_preview = time.time()
                        buffer = await asyncio.to_thread(UVC.frame_to_buffer, frame)
                        ns.embed, ns.png = embed, buffer.getvalue()
                    uns.cv_frame_time = time.time()

                while ns.run:
                    ns.heartbeat = time.time()
                    # Blocks until a newer frame exists; wakes at least every 0.25s
                    claim = await asyncio.to_thread(ring.wait_frame, last_seq, 0.25)

                    if claim is None:
                        continue

                    last_seq = claim.seq
                    uns_time = claim.time_ns

                    # CV is capped at CV_FPS even when the card runs faster;
                    # capture times jitter, so accept frames slightly early
                    if uns_time - last_cv_ns < 0.8e9 / CV_FPS:
                        claim.release()
                        continue

                    last_cv_ns = uns_time

                    # Release the shared slot before OCR so slow analysis cannot block capture.
                    try:
                        frame[:] = claim.frame
                    finally:
                        claim.release()
                    try:
                        embed = analyze_frame(frame, uns_time)
                        await publish_preview(embed)
                    except Exception:
                        logger.exception("CV frame processing failed; skipping frame.")

            asyncio.run(main_task())

        super().__init__(dman, dman.drive, ring=True)
        self.ns.heartbeat = time.time()
        self.uns.cv_frame_time = time.time()
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

    def restore_state(self, state):
        """Apply carried-over state, including the log path shared with NXBT."""
        super().restore_state(state)
        if "encounter_log" in state:
            self.uns.encounter_log = state["encounter_log"]

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
        engine = get_ocr()
        if not hasattr(engine, "predict"):
            # PaddleOCR 2.x is still installed; `pip install -e .` upgrades it
            result = engine.ocr(gray, cls=True)
            return "\n".join(line[1][0] for page in result for line in page or [])
        result = engine.predict(cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR))
        return "\n".join(text for page in result for text in page["rec_texts"])

    @staticmethod
    def scrape_text(buffer, *_, x=0, y=0, w=1920, h=1080):
        """Extract text from a frame crop, retrying OCR with inverted colors."""
        cropped = buffer[y : y + h, x : x + w]
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
        interval=1.0,
        reject=30,
    )
    afk_home_screen_scene = Scene(
        cv2.imread(str(SCENES_DIR / "switch_home_screen_afk.png")),
        y=720,
        h=200,
        interval=1.0,
        reject=30,
    )
    boot_screen_scene = Scene(
        cv2.imread(str(SCENES_DIR / "switch_boot_screen.png")),
        x=1580,
        y=920,
    )
    elgato_no_signal_scene = Scene(
        cv2.imread(str(SCENES_DIR / "elgato_no_signal.png")),
        interval=10.0,
        reject=30,
    )
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
    bdsp_bag_scene = Scene(
        cv2.imread(str(SCENES_DIR / "bdsp_bag.png")),
        w=204,
        h=89,
    )
