"""Capture video frames from the configured USB video device."""

import asyncio
import io
import logging
import subprocess
import threading
import time

import cv2
import numpy
import xxhash

from cynthia.utils.streamcfg import CV_FPS, capture_mode, size_for

from .daemon import Daemon
from .dman import FB0

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Uncompressed 4:2:2 from the card: lossless and cheaper to decode than MJPG
CAPTURE_FOURCC = "YUYV"
# The card delivers MJPG upside down but YUYV upright
CAPTURE_FLIP = CAPTURE_FOURCC != "YUYV"
# At 1080p the card's own NV12 is read untouched, so the encoders need no
# conversion; the BGR frames for CV and the web page are derived from it
NATIVE_FOURCC = "NV12"
NATIVE_BYTES = FB0.WIDTH * FB0.HEIGHT * 3 // 2
READ_FAILURE_TIMEOUT = 5
# A cheaper capture mode must hold this long before the card is reopened
DOWNGRADE_AFTER_SECONDS = 10


class UVCDaemon(Daemon):
    """Capture frames on a dedicated thread and publish them to the frame ring."""

    def __init__(self, dman):
        """Start the capture process, which publishes into the shared ring."""

        def loop(ns, uns, ring, native_ring, usb_id):
            """Supervise the capture thread, following the mode the streams need."""

            async def main_task():
                """Open the device, run the capture thread, and recover from errors."""
                uvc = UVC(usb_id)
                mode = None
                cheaper_since = None
                reset = True
                while ns.run:
                    wanted = capture_mode(uns)
                    if uvc.cap is not None and uvc.capturing and wanted != mode:
                        upgrade = wanted[0] > mode[0] or wanted[1] > mode[1]
                        cheaper_since = cheaper_since or time.monotonic()
                        if (
                            upgrade
                            or time.monotonic() - cheaper_since
                            > DOWNGRADE_AFTER_SECONDS
                        ):
                            logger.info(
                                "Capture mode %s -> %s",
                                mode_name(mode),
                                mode_name(wanted),
                            )
                            uvc.stop_capture()
                            uvc.release()
                            cheaper_since = None
                            reset = False
                    elif wanted == mode:
                        cheaper_since = None
                    if uvc.cap is None:
                        mode = wanted
                        await uvc.setup(*mode, reset=reset)
                        reset = True
                        uns.capture_mode = uvc.describe()
                        uns.capture_native = uvc.native
                        uvc.start_capture(ring, native_ring)
                    if not uvc.capturing:
                        # Capture dropped out; reopen (and USB reset) it
                        uvc.stop_capture()
                        uvc.release()
                        await asyncio.sleep(1)
                        continue
                    await asyncio.sleep(0.25)
                uvc.stop_capture()
                uvc.release()

            asyncio.run(main_task())

        super().__init__(
            dman,
            dman.context.env.get("ELGATO_USB_ID", None) or None,
            ring=True,
            native_ring=True,
        )
        self.loop = loop
        self.start()


class UVC:
    """Open a USB video capture device and read frames on a background thread."""

    def __init__(self, usb_id=None):
        """Store the capture card's `vendor:product` USB ID, if one is configured."""
        self.usb_id = usb_id
        self.width, self.height, self.fps = FB0.WIDTH, FB0.HEIGHT, CV_FPS
        self.cap = None
        self._thread = None
        self._stop = threading.Event()
        self.native = False

    def describe(self):
        """The mode the card is actually delivering, for stats."""
        return f"{self.width}x{self.height}@{self.fps}"

    async def setup(self, height=FB0.HEIGHT, fps=CV_FPS, reset=True):
        """Reset the USB device (when configured) and open the capture at a mode.

        The card is asked for `height` (16:9) at `fps`; what it actually grants
        is what `describe()` reports and what the capture loop reads.
        """
        if not reset:
            pass
        elif self.usb_id:
            result = subprocess.run(
                ["usbreset", self.usb_id], capture_output=True, text=True
            )
            logger.debug("usbreset: %s", result.stdout)
            await asyncio.sleep(2)  # Wait for the device to reset
        else:
            logger.warning("ELGATO_USB_ID is not set; skipping the USB reset.")

        width, height = size_for(height)
        native = (width, height) == (FB0.WIDTH, FB0.HEIGHT)
        self.cap = self._open(width, height, fps, native)
        if native:
            await asyncio.sleep(1)
            self.native = self._reads_native()
            if not self.native:
                logger.warning(
                    "The card gave no usable NV12; using %s.", CAPTURE_FOURCC
                )
                self.cap.release()
                self.cap = self._open(width, height, fps, False)
        else:
            self.native = False

        await asyncio.sleep(1)  # Give the camera some time to initialize
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or width
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or height
        self.fps = round(self.cap.get(cv2.CAP_PROP_FPS)) or fps
        logger.info("Capturing at %s.", self.describe())

    @staticmethod
    def _open(width, height, fps, native):
        """Open the device in NV12 (kept raw) or in the converted default format."""
        cap = cv2.VideoCapture(-1)
        # The pixel format must be chosen before the frame size and rate
        fourcc = NATIVE_FOURCC if native else CAPTURE_FOURCC
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
        if native:
            cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_FPS, fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _reads_native(self):
        """Whether the open device really delivers whole raw 1080p NV12 frames."""
        for _ in range(3):
            ok, raw = self.cap.read()
            if ok and raw is not None and raw.size == NATIVE_BYTES:
                return True
        return False

    @property
    def capturing(self):
        """Whether the capture thread is alive and healthy."""
        return self._thread is not None and self._thread.is_alive()

    def start_capture(self, ring, native_ring):
        """Start the thread that reads, hashes, and publishes frames."""
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._capture_loop,
            args=(ring, native_ring),
            name="uvc-capture",
            daemon=True,
        )
        self._thread.start()

    def stop_capture(self):
        """Ask the capture thread to finish and wait briefly for it."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            if self._thread.is_alive():
                logger.warning("Capture thread did not stop; leaving the device open.")
        self._thread = None

    def _capture_loop(self, ring, native_ring):
        """Read frames straight into free ring slots (the blocking call lives here)."""
        if self.native:
            return self._native_loop(ring, native_ring)
        # A card running below 1080p is read aside and scaled up into the ring
        direct = (self.width, self.height) == (FB0.WIDTH, FB0.HEIGHT)
        scratch = numpy.empty(
            FB0.shape() if direct else (self.height, self.width, FB0.CHANNELS),
            dtype=numpy.uint8,
        )
        failing_since = None
        while not self._stop.is_set():
            slot = ring.begin_write()
            target = scratch if slot is None or not direct else ring.view(slot)
            try:
                ok, _ = self.cap.read(target)
            except Exception:
                logger.exception("Capture read failed.")
                ok = False
            if not ok:
                if slot is not None:
                    ring.abort_write(slot)
                failing_since = failing_since or time.monotonic()
                if time.monotonic() - failing_since > READ_FAILURE_TIMEOUT:
                    logger.error("Failed to read frame from UVC device.")
                    return
                time.sleep(0.05)
                continue
            failing_since = None
            if slot is None:
                # No free slot: the frame was read to keep the device draining
                continue
            captured_at = time.time_ns()
            if not direct:
                target = ring.view(slot)
                cv2.resize(
                    scratch,
                    (FB0.WIDTH, FB0.HEIGHT),
                    dst=target,
                    interpolation=cv2.INTER_LINEAR,
                )
            if CAPTURE_FLIP:
                cv2.flip(target, 0, target)
            ring.end_write(slot, captured_at, xxhash.xxh3_64_intdigest(target.data))

    def _native_loop(self, ring, native_ring):
        """Publish each raw NV12 frame, and its BGR conversion for CV and the page."""
        failing_since = None
        while not self._stop.is_set():
            try:
                ok, raw = self.cap.read()
            except Exception:
                logger.exception("Capture read failed.")
                ok = False
            if ok and raw is not None and raw.size != NATIVE_BYTES:
                ok = False
            if not ok:
                failing_since = failing_since or time.monotonic()
                if time.monotonic() - failing_since > READ_FAILURE_TIMEOUT:
                    logger.error("Failed to read frame from UVC device.")
                    return
                time.sleep(0.05)
                continue
            failing_since = None
            captured_at = time.time_ns()
            raw = raw.reshape(FB0.native_shape())
            slot = ring.begin_write()
            if slot is not None:
                bgr = ring.view(slot)
                cv2.cvtColor(raw, cv2.COLOR_YUV2BGR_NV12, dst=bgr)
                frame_hash = xxhash.xxh3_64_intdigest(bgr.data)
                ring.end_write(slot, captured_at, frame_hash)
            else:
                frame_hash = 0
            native_slot = native_ring.begin_write()
            if native_slot is not None:
                native_ring.view(native_slot)[:] = raw
                native_ring.end_write(native_slot, captured_at, frame_hash)

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
            self.cap = None


def mode_name(mode):
    """Format a `(height, fps)` capture mode for logs."""
    return f"{mode[0]}p{mode[1]}"
