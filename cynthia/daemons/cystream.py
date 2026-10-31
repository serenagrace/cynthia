"""Serve captured video frames and bot status through a local web app."""

import asyncio
import gzip
import json
import logging
import zlib
from contextlib import asynccontextmanager, closing
from multiprocessing import shared_memory
from pathlib import Path

import cv2
import numpy
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

from .daemon import Daemon
from .dman import FB0

SITE_DIR = Path(__file__).resolve().parent.parent / "site"
ASOUND_CARDS = Path("/proc/asound/cards")


def find_audio_device(env=None):
    """Return the ALSA capture device: `AUDIO_DEVICE`, else the Elgato card."""
    configured = env.get("AUDIO_DEVICE", None) if env is not None else None
    if configured:
        return configured
    try:
        for line in ASOUND_CARDS.read_text().splitlines():
            if "elgato" in line.lower() and "[" in line:
                card_id = line.split("[", 1)[1].split("]", 1)[0].strip()
                return f"plughw:CARD={card_id}"
    except OSError:
        pass
    return None


def create_app(drive, ns, uns, fb, audio_device=None):
    """Build the FastAPI app that streams frames and serves status endpoints."""
    viewers = {"count": 0}
    latest = {"seq": 0, "chunk": None}
    last_status = {}
    last_stats = {}

    def encode(frame):
        """Downscale a frame to 720p and encode it as high-quality JPEG bytes."""
        success, buffer = cv2.imencode(
            ".jpg",
            cv2.resize(frame, (1280, 720), interpolation=cv2.INTER_AREA),
            (
                cv2.IMWRITE_JPEG_QUALITY,
                90,
                cv2.IMWRITE_JPEG_OPTIMIZE,
                1,
                cv2.IMWRITE_JPEG_SAMPLING_FACTOR,
                cv2.IMWRITE_JPEG_SAMPLING_FACTOR_444,
            ),
        )
        return buffer.tobytes() if success else None

    async def encoder():
        """Encode new shared-memory frames while viewers are connected."""
        while ns.run:
            if viewers["count"] == 0 or uns.fbptr is None:
                await asyncio.sleep(0.05)
                continue
            fbptr = uns.fbptr
            uns_time = uns.uvc_time1 if fbptr else uns.uvc_time0
            if ns.uvc_time == uns_time:
                await asyncio.sleep(0.01)
                continue
            ns.uvc_time = uns_time
            jpeg = await asyncio.to_thread(encode, fb[fbptr])
            if jpeg is not None:
                latest["chunk"] = (
                    b"--frame\r\n" b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                )
                latest["seq"] += 1
            await asyncio.sleep(0.03)

    @asynccontextmanager
    async def lifespan(_):
        """Start the frame encoder with the app and cancel it on shutdown."""
        task = asyncio.create_task(encoder())
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    app = FastAPI(lifespan=lifespan)
    app.state.viewers = viewers
    app.state.latest = latest

    async def frame_generator():
        """Yield newly encoded multipart frames to a streaming response."""
        viewers["count"] += 1
        last_seq = latest["seq"]
        try:
            while ns.run:
                if latest["seq"] != last_seq:
                    last_seq = latest["seq"]
                    yield latest["chunk"]
                else:
                    await asyncio.sleep(0.01)
        finally:
            viewers["count"] -= 1

    @app.get("/api/user_status")
    async def status():
        """Return the saved user status mapping."""
        if not drive.enabled:
            return {}
        try:
            with drive.open("user_status.json", "r", touch=True) as f:
                status_data = json.load(f)
            if status_data is None:
                # The status writer dumps null when no activity is available
                status_data = {}
            last_status.clear()
            last_status.update(status_data)
        except json.JSONDecodeError:
            # The writer truncates before writing; serve the last good value
            status_data = dict(last_status)
        return status_data

    @app.get("/api/activity_stats")
    async def activity_stats():
        """Return raw activity timestamps; the site computes durations."""
        if not drive.enabled:
            return {}
        try:
            with drive.open("activity_stats.json", "r", touch=True) as f:
                stats = json.load(f)
            last_stats.clear()
            last_stats.update(stats or {})
        except json.JSONDecodeError:
            stats = dict(last_stats)
        return stats or {}

    @app.get("/api/ssim_data")
    async def ssim_data():
        """Return the top 5 SSIM scene match scores from the CV daemon."""
        scores = getattr(uns, "ssim_scores", None) or []
        return {"scores": [{"scene": k, "score": float(v)} for k, v in scores[:5]]}

    @app.get("/api/inputs")
    async def inputs():
        """Return the controller buttons macros are currently pressing."""
        return {"pressed": list(getattr(uns, "pressed_buttons", None) or [])}

    @app.get("/api/viewers")
    async def viewer_count():
        """Return the current number of video stream viewers."""
        return {"viewers": viewers["count"]}

    async def audio_generator():
        """Yield MP3 chunks from an ffmpeg capture that lives with the listener."""
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-fflags",
            "nobuffer",
            "-flags",
            "low_delay",
            "-probesize",
            "32",
            "-analyzeduration",
            "0",
            "-thread_queue_size",
            "1024",
            "-f",
            "alsa",
            "-i",
            audio_device,
            "-af",
            "highpass=f=20,aresample=async=1000",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            "-flush_packets",
            "1",
            "-f",
            "mp3",
            "-",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            while ns.run:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                yield chunk
        finally:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()

    @app.get("/api/audio_stream")
    async def audio_stream():
        """Stream captured game audio as MP3 while a listener is connected."""
        if not audio_device:
            raise HTTPException(status_code=503, detail="No audio device")
        return StreamingResponse(
            audio_generator(),
            media_type="audio/mpeg",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.get("/video_feed", response_class=HTMLResponse)
    async def video_feed_page():
        """Serve the local HTML page for the video stream."""
        html_content = (SITE_DIR / "html" / "video_feed.html").read_text()
        return HTMLResponse(content=html_content, status_code=200)

    @app.get("/api/stream_endpoint")
    async def video_feed():
        """Stream captured frames as a multipart MJPEG response."""
        ns.uvc_hash = -1
        return StreamingResponse(
            frame_generator(),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    return app


class GzipLogHandler(logging.StreamHandler):
    """Appends log lines to a .gz file, flushed per record so it stays readable."""

    def __init__(self, path):
        """Open a gzip log stream and format each record with a timestamp."""
        super().__init__(gzip.open(path, "at", encoding="utf-8"))
        self.setFormatter(logging.Formatter("%(asctime)s %(message)s"))

    def flush(self):
        """Flush the log record and sync the gzip stream."""
        super().flush()
        self.stream.buffer.flush(zlib_mode=zlib.Z_SYNC_FLUSH)

    def close(self):
        """Close the stream handler and its gzip file."""
        super().close()
        self.stream.close()


class CYStream(Daemon):
    """Run the local FastAPI video and status service in a process."""

    def __init__(self, dman):
        """Create the web worker and attach compressed access logging."""

        def loop(ns, uns, fba, fbb, drive, audio_device):
            """Serve the FastAPI app over the local HTTP interface."""
            with (
                closing(shared_memory.SharedMemory(name=fba)) as shmA,
                closing(shared_memory.SharedMemory(name=fbb)) as shmB,
            ):
                shms = (shmA, shmB)
                fb = list(
                    numpy.ndarray(FB0.shape(), dtype=numpy.uint8, buffer=shms[idx].buf)
                    for idx in (0, 1)
                )
                app = create_app(drive, ns, uns, fb, audio_device)
                ns.done = True
                config = uvicorn.Config(
                    app,
                    host="127.0.0.1",
                    port=8000,
                    log_config=None,
                    access_log=True,
                )
                # Config() sets both uvicorn loggers to one level; split them afterwards
                logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
                access = logging.getLogger("uvicorn.access")
                access.setLevel(logging.INFO)
                access.propagate = False
                access_path = drive.path("uvicorn_access.log.gz")
                if access_path is not None:
                    access.addHandler(GzipLogHandler(access_path))
                uvicorn.Server(config).run()

        super().__init__(
            dman,
            dman.drive,
            find_audio_device(dman.context.env),
            fbs=(0,),
        )
        self.ns.uvc_time = -1
        self.ns.done = False
        self.loop = loop
        self.start()
