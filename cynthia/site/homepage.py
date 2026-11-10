"""Small public snapshots, independent of the streaming encoder and viewers."""

import re
import threading
import time

import cv2
from fastapi import HTTPException, Response

from cynthia.utils.streamcfg import shows_no_signal

CAPTURE_MAX_AGE_S = 5
TWITCH_MAX_AGE_S = 75
THUMBNAIL_INTERVAL_S = 5


def register_homepage_api(app, ns, uns, ring, twitch_channel):
    """Expose only a public destination and a bounded, cached capture thumbnail."""
    lock = threading.Lock()
    thumbnail = {"jpeg": None, "at": 0.0}
    channel = str(twitch_channel or "")
    valid_channel = re.fullmatch(r"[A-Za-z0-9_]{1,25}", channel)

    def available():
        try:
            age = (time.time_ns() - ring.last_time_ns) / 1e9 if ring else -1
            return bool(
                ns.run
                and ring is not None
                and ring.seq > 0
                and 0 <= age < CAPTURE_MAX_AGE_S
                and not shows_no_signal(uns)
            )
        except (AttributeError, EOFError, OSError):
            return False

    @app.get("/api/homepage_status")
    def homepage_status(response: Response):
        """Prefer recently verified Twitch live state, never OBS/test mode."""
        response.headers["Cache-Control"] = "no-store"
        if not available():
            return {"visible": False}
        try:
            state = getattr(uns, "homepage_twitch", {}) or {}
            age = time.time() - float(state.get("checked_at", 0))
            live = (
                valid_channel
                and state.get("live") is True
                and state.get("channel", "").lower() == channel.lower()
                and 0 <= age < TWITCH_MAX_AGE_S
            )
        except (AttributeError, TypeError, ValueError, EOFError, OSError):
            live = False
        return {
            "visible": True,
            "label": "Live on Twitch" if live else "Watch CYStream",
            "url": f"https://www.twitch.tv/{channel}" if live else "/video_feed",
            "thumbnail": "/api/homepage_thumbnail",
        }

    @app.get("/api/homepage_thumbnail")
    def homepage_thumbnail():
        """Read one claimed frame at most every five seconds; never add a viewer."""
        with lock:
            if not available():
                thumbnail.update(jpeg=None, at=0.0)
                raise HTTPException(503, "Capture unavailable")
            now = time.monotonic()
            if (
                thumbnail["jpeg"] is None
                or now - thumbnail["at"] >= THUMBNAIL_INTERVAL_S
            ):
                claim = ring.wait_frame(0, 0)
                if claim is None:
                    raise HTTPException(503, "Capture unavailable")
                try:
                    if (
                        not 0
                        <= (time.time_ns() - claim.time_ns) / 1e9
                        < CAPTURE_MAX_AGE_S
                    ):
                        raise HTTPException(503, "Capture unavailable")
                    frame = cv2.resize(
                        claim.frame, (480, 270), interpolation=cv2.INTER_AREA
                    )
                finally:
                    claim.release()
                ok, data = cv2.imencode(".jpg", frame, (cv2.IMWRITE_JPEG_QUALITY, 75))
                if not ok:
                    raise HTTPException(503, "Capture unavailable")
                thumbnail.update(jpeg=data.tobytes(), at=now)
            if not available():
                raise HTTPException(503, "Capture unavailable")
            return Response(
                thumbnail["jpeg"],
                media_type="image/jpeg",
                headers={"Cache-Control": "no-store"},
            )
