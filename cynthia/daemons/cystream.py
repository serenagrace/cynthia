import asyncio
from contextlib import asynccontextmanager, closing
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
                viewers = {"count": 0}
                latest = {"seq": 0, "chunk": None}

                def encode(frame):
                    success, buffer = cv2.imencode(
                        ".jpg",
                        cv2.resize(
                            frame, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA
                        ),
                    )
                    return buffer.tobytes() if success else None

                async def encoder():
                    # Encode each new frame once, however many viewers there are
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
                                b"--frame\r\n"
                                b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                            )
                            latest["seq"] += 1
                        await asyncio.sleep(0.03)

                @asynccontextmanager
                async def lifespan(_):
                    task = asyncio.create_task(encoder())
                    try:
                        yield
                    finally:
                        task.cancel()

                app = FastAPI(lifespan=lifespan)

                def main_task():
                    async def frame_generator():
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
                        try:
                            with drive.open("user_status.json", "r", touch=True) as f:
                                status = json.load(f)
                        except json.JSONDecodeError:
                            status = {}
                        return status

                    @app.get("/api/viewers")
                    async def viewer_count():
                        return {"viewers": viewers["count"]}

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
