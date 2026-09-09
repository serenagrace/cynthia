import asyncio
from contextlib import closing
import cv2
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import json
import numpy
from multiprocessing import shared_memory
from .daemon import Daemon
from .dman import FB0
import uvicorn


class CYStream(Daemon):
    def __init__(self, dman):
        def loop(ns, uns, fba, fbb, drive):
            with (
                closing(shared_memory.SharedMemory(name=fba)) as shmA,
                closing(shared_memory.SharedMemory(name=fbb)) as shmB,
            ):
                shms = (shmA, shmB)
                fb = list(
                    numpy.ndarray(FB0.shape(), dtype=numpy.uint8, buffer=shms[idx].buf)
                    for idx in (0, 1)
                )
                app = FastAPI()

                def main_task():
                    async def frame_generator():
                        while ns.run:
                            while uns.fbptr is None:
                                await asyncio.sleep(0.01)
                            fbptr = uns.fbptr
                            uns_time = uns.uvc_time1 if fbptr else uns.uvc_time0
                            if ns.uvc_time != uns_time:
                                ns.uvc_time = uns_time
                                success, buffer = cv2.imencode(
                                    ".jpg",
                                    cv2.resize(
                                        fb[fbptr],
                                        None,
                                        fx=0.5,
                                        fy=0.5,
                                        interpolation=cv2.INTER_CUBIC,
                                    ),
                                )
                                if success:
                                    yield (
                                        b"--frame\r\n"
                                        b"Content-Type: image/jpeg\r\n\r\n"
                                        + buffer.tobytes()
                                        + b"\r\n"
                                    )
                                    await asyncio.sleep(0.03)
                            else:
                                await asyncio.sleep(0.05)

                    @app.get("/api/user_status")
                    async def status():
                        try:
                            with drive.open("user_status.json", "r", touch=True) as f:
                                status = json.load(f)
                        except json.JSONDecodeError:
                            status = {}
                        return status

                    @app.get("/favicon.ico", include_in_schema=False)
                    async def favicon():
                        return FileResponse(
                            "/raidarchive/cynthia_drive/site/static/favicon.ico"
                        )

                    @app.get("/video_feed", response_class=HTMLResponse)
                    async def video_feed_page():
                        html_content = ""
                        with drive.open("site/html/video_feed.html", "r") as f:
                            html_content = f.read()
                        return HTMLResponse(content=html_content, status_code=200)

                    @app.get("/api/stream_endpoint")
                    async def video_feed():
                        ns.uvc_hash = -1
                        return StreamingResponse(
                            frame_generator(),
                            media_type="multipart/x-mixed-replace; boundary=frame",
                        )

                    ns.done = True
                    uvicorn.run(app, host="127.0.0.1", port=8000)

                main_task()

        super().__init__(dman, dman.drive, fbs=(0,))
        self.ns.uvc_time = -1
        self.ns.done = False
        self.loop = loop
        self.start()
