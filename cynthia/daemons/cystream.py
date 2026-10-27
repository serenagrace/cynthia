"""Serve captured video frames and bot status through a local web app."""

import asyncio
import gzip
import json
import logging
import zlib
from contextlib import asynccontextmanager, closing
from multiprocessing import shared_memory

import cv2
import numpy
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse

from .daemon import Daemon
from .dman import FB0


def create_app(drive, ns, uns, fb):
    """Build the FastAPI app that streams frames and serves status endpoints."""
    viewers = {"count": 0}
    latest = {"seq": 0, "chunk": None}

    def encode(frame):
        """Resize a frame and encode it as JPEG bytes."""
        success, buffer = cv2.imencode(
            ".jpg",
            cv2.resize(frame, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA),
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
        try:
            with drive.open("user_status.json", "r", touch=True) as f:
                status_data = json.load(f)
        except json.JSONDecodeError:
            status_data = {}
        return status_data

    @app.get("/api/viewers")
    async def viewer_count():
        """Return the current number of video stream viewers."""
        return {"viewers": viewers["count"]}

    @app.get("/video_feed", response_class=HTMLResponse)
    async def video_feed_page():
        """Serve the local HTML page for the video stream."""
        with drive.open("site/html/video_feed.html", "r") as f:
            html_content = f.read()
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

        def loop(ns, uns, fba, fbb, drive):
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
                app = create_app(drive, ns, uns, fb)
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

        super().__init__(dman, dman.drive, fbs=(0,))
        self.ns.uvc_time = -1
        self.ns.done = False
        self.loop = loop
        self.start()
