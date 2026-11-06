"""Serve captured video frames and bot status through a local web app."""

import asyncio
import gzip
import json
import logging
import os
import time
import urllib.error
import urllib.request
import zlib
from collections import OrderedDict, deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse

from cynthia.utils.obslayout import OBS_SYNC_MAX_DELAY_MS, overlay_delay_ms
from cynthia.utils.streamcfg import CV_FPS, setting, size_for
from cynthia.utils.twitchchat import TwitchChat
from cynthia.utils.version import display_version

from .daemon import Daemon
from .frames import AUDIO_BYTES_PER_SEC

SITE_DIR = Path(__file__).resolve().parent.parent / "site"


CACHE_BYTES = 64 * 1024 * 1024
JPEG_QUALITY = 85
# A listener this far behind the live edge is moved forward instead of lagging.
# Generous, because skipping audio is audible; brief stalls are absorbed instead.
AUDIO_MAX_LAG_MS = 1500
AUDIO_START_LAG_MS = 60
# Video is held back this long so the audio buffer can ride out hiccups in sync
DEFAULT_VIDEO_DELAY_MS = 1000
AUDIO_ENCODER = [
    "ffmpeg",
    "-nostdin",
    "-loglevel",
    "error",
    "-f",
    "s16le",
    "-ar",
    "48000",
    "-ac",
    "2",
    "-i",
    "pipe:0",
    "-c:a",
    "libmp3lame",
    "-b:a",
    "192k",
    "-flush_packets",
    "1",
    "-f",
    "mp3",
    "-",
]


class JpegCache:
    """Byte-budgeted LRU of encoded frames keyed by frame hash."""

    def __init__(self, budget=CACHE_BYTES):
        """Create an empty cache holding at most `budget` bytes."""
        self.budget = budget
        self.size = 0
        self.items = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key):
        """Return the cached bytes for `key`, refreshing its recency."""
        value = self.items.get(key)
        if value is None:
            self.misses += 1
            return None
        self.items.move_to_end(key)
        self.hits += 1
        return value

    def put(self, key, value):
        """Store bytes, evicting the least recently used entries over budget."""
        if key in self.items or len(value) > self.budget:
            return
        self.items[key] = value
        self.size += len(value)
        while self.size > self.budget:
            _, old = self.items.popitem(last=False)
            self.size -= len(old)


def encode_jpeg(frame, height=720):
    """Downscale a frame to `height` (16:9) and encode it as JPEG bytes (4:2:0)."""
    size = size_for(height)
    if frame.shape[1] != size[0]:
        frame = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
    success, buffer = cv2.imencode(
        ".jpg",
        frame,
        (
            cv2.IMWRITE_JPEG_QUALITY,
            JPEG_QUALITY,
            cv2.IMWRITE_JPEG_SAMPLING_FACTOR,
            cv2.IMWRITE_JPEG_SAMPLING_FACTOR_420,
        ),
    )
    return buffer.tobytes() if success else None


PANES = ("status", "ssim", "stats", "chat", "inputs", "watermark")


def app_version():
    """The running Cynthia version (`-alpha` when unreleased), or "dev"."""
    return display_version()


def render_page(name):
    """Read a site page, inlining the shared controller pad and the version."""
    html = (SITE_DIR / "html" / name).read_text()
    html = html.replace("<!--VERSION-->", app_version())
    return html.replace("<!--PAD-->", (SITE_DIR / "html" / "pad.html").read_text())


HISTORY_STEP_S = 0.05


def spoken_duration(seconds):
    """Format a duration as its two largest units, e.g. "3 hours and 5 minutes"."""
    seconds = max(0, int(seconds))
    units = [
        ("day", seconds // 86400),
        ("hour", seconds // 3600 % 24),
        ("minute", seconds // 60 % 60),
        ("second", seconds % 60),
    ]
    # Start at the largest nonzero unit, but always show minutes and seconds
    first = min(
        next((i for i, (_, amount) in enumerate(units) if amount), 2), len(units) - 2
    )
    return " and ".join(
        f"{amount} {unit}{'' if amount == 1 else 's'}"
        for unit, amount in units[first : first + 2]
    )


def describe_activity(stats):
    """Describe the hunt, else the custom status, for a chat command."""
    hunt = stats.get("hunt")
    if hunt:
        if stats.get("self_encounter"):
            return f"trying to get a shiny {hunt.title()}"
        return f"hunting shiny {hunt.title()}"
    if stats.get("status"):
        return stats["status"]
    return "not doing anything in particular right now"


def create_app(
    drive,
    ns,
    uns,
    ring,
    audio_ring=None,
    video_delay_ms=DEFAULT_VIDEO_DELAY_MS,
    twitch_channel=None,
    obs_delay_ms=0,
):
    """Build the FastAPI app that streams frames and serves status endpoints."""
    viewers = {"count": 0}
    chat = TwitchChat(twitch_channel) if twitch_channel else None
    latest = {"seq": 0, "chunk": None, "ns": 0}
    last_status = {}
    last_stats = {}
    cache = JpegCache()
    wake = {"viewers": None, "frame": None}
    audio_stats = {"listeners": 0, "skipped_bytes": 0}
    sync = {"video_latency_ms": 60.0}
    # Recent input and SSIM samples, so the web view can show them as late as its video
    history = deque(
        maxlen=int(
            max(video_delay_ms, obs_delay_ms, OBS_SYNC_MAX_DELAY_MS)
            / HISTORY_STEP_S
            / 1000
        )
        + 40
    )
    # Cumulative counters; clients difference successive polls to get rates
    stream_stats = {"encoded": 0, "sent": 0, "encode_ms": 0.0, "jpeg_bytes": 0.0}

    def encode_next(after_seq, last_ns):
        """Block for a newer frame within the fps budget and encode (or reuse) it."""
        claim = ring.wait_frame(after_seq, 0.25)
        if claim is None:
            return after_seq, last_ns, None
        try:
            # Capture timestamps jitter, so allow frames slightly early
            if claim.time_ns - last_ns < 0.8e9 / setting(uns, "web_fps"):
                return claim.seq, last_ns, None
            height = setting(uns, "web_height")
            key = (claim.hash, height)
            jpeg = cache.get(key)
            if jpeg is None:
                started = time.perf_counter()
                jpeg = encode_jpeg(claim.frame, height)
                if jpeg is not None:
                    cache.put(key, jpeg)
                    took = (time.perf_counter() - started) * 1000
                    stream_stats["encode_ms"] += 0.1 * (
                        took - stream_stats["encode_ms"]
                    )
            return claim.seq, claim.time_ns, (jpeg, claim.time_ns) if jpeg else None
        finally:
            claim.release()

    async def encoder():
        """Encode new ring frames, idling completely while nobody is watching."""
        after_seq, last_ns = 0, 0
        while ns.run:
            if viewers["count"] == 0:
                wake["viewers"].clear()
                await wake["viewers"].wait()
                continue
            after_seq, last_ns, jpeg = await asyncio.to_thread(
                encode_next, after_seq, last_ns
            )
            if jpeg is not None:
                async with wake["frame"]:
                    jpeg, captured_ns = jpeg
                    # Smoothed capture-to-ready delay of the video path
                    delay_ms = (time.time_ns() - captured_ns) / 1e6
                    sync["video_latency_ms"] += 0.1 * (
                        delay_ms - sync["video_latency_ms"]
                    )
                    # X-Capture-Ns lets clients measure how old each frame is
                    latest["chunk"] = (
                        b"--frame\r\nContent-Type: image/jpeg\r\n"
                        + b"X-Capture-Ns: %d\r\n\r\n" % captured_ns
                        + jpeg
                        + b"\r\n"
                    )
                    latest["ns"] = captured_ns
                    stream_stats["encoded"] += 1
                    stream_stats["jpeg_bytes"] += 0.1 * (
                        len(jpeg) - stream_stats["jpeg_bytes"]
                    )
                    latest["seq"] += 1
                    wake["frame"].notify_all()

    async def sampler():
        """Record the current inputs and SSIM scores a few times a second."""
        while True:
            history.append(
                (
                    time.monotonic(),
                    list(getattr(uns, "pressed_buttons", None) or []),
                    list(getattr(uns, "ssim_scores", None) or []),
                )
            )
            await asyncio.sleep(HISTORY_STEP_S)

    def sample(delayed, feed="web"):
        """Return (pressed, scores): live, or as they were one feed's delay ago.

        `feed="obs"` uses the OBS feed delay; anything else the web stream's.
        """
        delay_ms = (
            overlay_delay_ms(uns, obs_delay_ms) if feed == "obs" else video_delay_ms
        )
        if delayed and delay_ms and history:
            cutoff = time.monotonic() - delay_ms / 1000
            for stamp, pressed, scores in reversed(history):
                if stamp <= cutoff:
                    return pressed, scores
            return [], []
        return (
            list(getattr(uns, "pressed_buttons", None) or []),
            list(getattr(uns, "ssim_scores", None) or []),
        )

    @asynccontextmanager
    async def lifespan(_):
        """Start the frame encoder with the app and cancel it on shutdown."""
        wake["viewers"] = asyncio.Event()
        wake["frame"] = asyncio.Condition()
        tasks = [asyncio.create_task(encoder()), asyncio.create_task(sampler())]
        if chat is not None:
            tasks.append(asyncio.create_task(chat.run()))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(lifespan=lifespan)
    app.state.viewers = viewers
    app.state.latest = latest
    app.state.cache = cache

    async def frame_generator():
        """Yield newly encoded multipart frames to a streaming response."""
        viewers["count"] += 1
        uns.web_viewers = viewers["count"]
        wake["viewers"].set()
        last_seq = 0
        delay_ns = int(video_delay_ms * 1e6)
        pending = deque()  # (capture time, chunk) waiting out the video delay
        try:
            while ns.run:
                async with wake["frame"]:
                    if latest["seq"] == last_seq:
                        wait = 1.0
                        if pending:
                            due = pending[0][0] + delay_ns - time.time_ns()
                            wait = min(wait, max(0.001, due / 1e9))
                        try:
                            await asyncio.wait_for(
                                wake["frame"].wait_for(
                                    lambda: latest["seq"] != last_seq
                                ),
                                timeout=wait,
                            )
                        except asyncio.TimeoutError:
                            pass
                    if latest["seq"] != last_seq:
                        last_seq = latest["seq"]
                        pending.append((latest["ns"], latest["chunk"]))
                now = time.time_ns()
                while pending and pending[0][0] + delay_ns <= now:
                    stream_stats["sent"] += 1
                    yield pending.popleft()[1]
        finally:
            viewers["count"] -= 1
            uns.web_viewers = viewers["count"]

    def read_activity_stats():
        """Return the saved activity stats, or the last good copy mid-write."""
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

    @app.get("/api/streamelements/uptime", response_class=PlainTextResponse)
    async def streamelements_uptime():
        """Return how long the bot has been running, as text for StreamElements."""
        started = read_activity_stats().get("bot_started")
        if not isinstance(started, (int, float)):
            return "isn't running right now"
        return f"has been running for {spoken_duration(time.time() - started / 1000)}"

    @app.get("/api/streamelements/online", response_class=PlainTextResponse)
    async def streamelements_online():
        """Answer "True" while the bot's web server is up, for StreamElements."""
        return "True"

    @app.get("/api/streamelements/description", response_class=PlainTextResponse)
    async def streamelements_description():
        """Return the current hunt or status, as text for StreamElements."""
        return describe_activity(read_activity_stats())

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
        return read_activity_stats()

    @app.get("/api/ssim_data")
    async def ssim_data(delayed: bool = False, feed: str = "web"):
        """Return the top 5 SSIM scene match scores from the CV daemon.

        `delayed=true` lags them to match the video: by the web stream delay,
        or by the OBS feed delay with `feed=obs`.
        """
        scores = sample(delayed, feed)[1]
        return {"scores": [{"scene": k, "score": float(v)} for k, v in scores[:5]]}

    @app.get("/api/inputs")
    async def inputs(delayed: bool = False, feed: str = "web"):
        """Return the controller buttons macros are currently pressing.

        `delayed=true` lags them to match the video: by the web stream delay,
        or by the OBS feed delay with `feed=obs`.
        """
        return {"pressed": sample(delayed, feed)[0]}

    @app.get("/api/viewers")
    async def viewer_count():
        """Return the current number of viewers, over MJPEG and WebRTC."""
        return {"viewers": viewers["count"] + getattr(uns, "webrtc_viewers", 0)}

    async def audio_generator():
        """Encode live PCM from the ring to MP3 for one listener."""
        proc = await asyncio.create_subprocess_exec(
            *AUDIO_ENCODER,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

        async def feed():
            """Pump ring audio into the encoder, catching up if it falls behind."""
            # Own thread: the shared pool is busy with JPEG encoding and a late
            # read would put a gap in the audio
            reader = ThreadPoolExecutor(max_workers=1, thread_name_prefix="audio")
            loop = asyncio.get_running_loop()
            pos = audio_ring.live_position(AUDIO_START_LAG_MS)
            silence = bytes(AUDIO_BYTES_PER_SEC // 10)
            try:
                while ns.run:
                    data, pos, _, skipped = await loop.run_in_executor(
                        reader, audio_ring.read, pos, 0.1, AUDIO_MAX_LAG_MS
                    )
                    # No capture data: send silence so the player never stalls
                    proc.stdin.write(data or silence)
                    await proc.stdin.drain()
                    if skipped:
                        audio_stats["skipped_bytes"] += skipped
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                reader.shutdown(wait=False)
                proc.stdin.close()

        feeder = asyncio.create_task(feed())
        audio_stats["listeners"] += 1
        uns.audio_listeners = audio_stats["listeners"]
        try:
            while ns.run:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                yield chunk
        finally:
            audio_stats["listeners"] -= 1
            uns.audio_listeners = audio_stats["listeners"]
            feeder.cancel()
            await asyncio.gather(feeder, return_exceptions=True)
            if proc.returncode is None:
                proc.kill()
            await proc.wait()

    @app.get("/api/audio_stream")
    async def audio_stream():
        """Stream live game audio as MP3 while a listener is connected."""
        if audio_ring is None:
            raise HTTPException(status_code=503, detail="No audio ring")
        return StreamingResponse(
            audio_generator(),
            media_type="audio/mpeg",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/webrtc")
    async def webrtc_info():
        """Report whether WebRTC is available and ask for its feed to be running."""
        ready = bool(getattr(uns, "webrtc_ready", False))
        if ready:
            uns.webrtc_requested = time.time()
        return {"enabled": ready}

    def whep_exchange(offer):
        """Forward a WHEP offer to MediaMTX; returns (status, answer, location)."""
        port = getattr(uns, "webrtc_port", 8889)
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/cynthia/whep",
            data=offer,
            headers={"Content-Type": "application/sdp"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as res:
                return res.status, res.read(), res.headers.get("Location")
        except urllib.error.HTTPError as e:
            return e.code, e.read(), None
        except OSError:
            return 503, b"", None

    @app.post("/api/whep")
    async def whep(request: Request):
        """Exchange a browser's WebRTC offer for MediaMTX's answer."""
        if not getattr(uns, "webrtc_ready", False):
            raise HTTPException(status_code=503, detail="WebRTC is unavailable")
        uns.webrtc_requested = time.time()
        offer = await request.body()
        status, answer, _ = await asyncio.to_thread(whep_exchange, offer)
        return Response(
            content=answer,
            status_code=status,
            media_type="application/sdp",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/sync")
    async def sync_info():
        """Return the video path delay the page uses to line audio up with it."""
        return {"video_latency_ms": round(sync["video_latency_ms"] + video_delay_ms, 1)}

    @app.get("/api/stream_stats")
    async def stream_info():
        """Return cumulative video and audio encode counters for the stats overlay."""
        return {
            "server_ns": time.time_ns(),
            "capture_seq": ring.seq,
            "capture_dropped": ring.dropped,
            "capture_age_ms": (
                round((time.time_ns() - ring.last_time_ns) / 1e6, 1)
                if ring.last_time_ns
                else None
            ),
            "encoded_frames": stream_stats["encoded"],
            "sent_frames": stream_stats["sent"],
            "encode_ms": round(stream_stats["encode_ms"], 2),
            "jpeg_kb": round(stream_stats["jpeg_bytes"] / 1024, 1),
            "cache_hits": cache.hits,
            "cache_misses": cache.misses,
            "cpu_load": [round(v, 2) for v in os.getloadavg()],
            "cpu_count": os.cpu_count() or 1,
            "viewers": viewers["count"] + getattr(uns, "webrtc_viewers", 0),
            "mjpeg_viewers": viewers["count"],
            "webrtc_viewers": getattr(uns, "webrtc_viewers", 0),
            "capture_mode": getattr(uns, "capture_mode", None),
            "web_fps": setting(uns, "web_fps"),
            "web_height": setting(uns, "web_height"),
            "obs_fps": setting(uns, "obs_fps"),
            "obs_height": setting(uns, "obs_height"),
            "cv_fps": CV_FPS,
            "video_delay_ms": video_delay_ms,
            "obs_overlay_delay_ms": overlay_delay_ms(uns, obs_delay_ms),
            "video_latency_ms": round(sync["video_latency_ms"] + video_delay_ms, 1),
            "audio": {
                **audio_stats,
                "captured": audio_ring is not None and audio_ring.last_time_ns > 0,
            },
        }

    @app.get("/api/audio_stats")
    async def audio_info():
        """Return listener count and how much audio was skipped to catch up."""
        return {
            **audio_stats,
            "captured": audio_ring is not None and audio_ring.last_time_ns > 0,
        }

    @app.get("/video_feed", response_class=HTMLResponse)
    async def video_feed_page():
        """Serve the local HTML page for the video stream."""
        return HTMLResponse(content=render_page("video_feed.html"), status_code=200)

    @app.get("/pane/{kind}", response_class=HTMLResponse)
    async def pane_page(kind: str):
        """Serve one overlay pane; OBS shows these as browser sources."""
        if kind not in PANES:
            raise HTTPException(status_code=404, detail="Unknown pane")
        return HTMLResponse(content=render_page("overlay.html"), status_code=200)

    @app.get("/api/twitch_chat")
    async def twitch_chat():
        """Return the latest Twitch chat messages (empty without a channel)."""
        return {"messages": chat.recent() if chat else []}

    @app.get("/api/stream_endpoint")
    async def video_feed():
        """Stream captured frames as a multipart MJPEG response."""
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

        def loop(
            ns,
            uns,
            ring,
            audio_ring,
            drive,
            video_delay_ms,
            twitch_channel,
            obs_delay_ms,
        ):
            """Serve the FastAPI app over the local HTTP interface."""
            app = create_app(
                drive,
                ns,
                uns,
                ring,
                audio_ring,
                video_delay_ms,
                twitch_channel,
                obs_delay_ms,
            )
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
            max(
                0,
                int(dman.context.config.get("stream_delay_ms", DEFAULT_VIDEO_DELAY_MS)),
            ),
            dman.context.env.get("TWITCH_CHANNEL", None) or None,
            max(
                0,
                int(dman.context.config.get("obs_feed_delay_ms", 0))
                + int(dman.context.config.get("obs_overlay_lag_ms", 0)),
            ),
            ring=True,
            audio_ring=True,
        )
        self.ns.done = False
        self.loop = loop
        self.start()
