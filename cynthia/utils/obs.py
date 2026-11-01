"""Control OBS Studio through obs-websocket (built into OBS 28 and newer)."""

import base64
import logging
import threading

import obsws_python as obsws
from obsws_python.error import OBSSDKError, OBSSDKRequestError

from .obslayout import (
    DEFAULT_CSS,
    SOURCE_PREFIX,
    VIDEO_SOURCE,
    pane_geometry,
    pane_url,
    source_name,
)
from .streamcfg import size_for

logger = logging.getLogger(__name__)
# The SDK logs a traceback for every refused connection; we report those ourselves
logging.getLogger("obsws_python").setLevel(logging.CRITICAL)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4455
OUTPUT_RUNNING = 501  # obs-websocket: the request needs the output stopped
TWITCH_SERVICE = {"service": "Twitch", "server": "auto"}
BANDWIDTH_TEST_SUFFIX = "?bandwidthtest=true"
MANAGED_KINDS = ("browser_source", "ffmpeg_source")


class OBSError(RuntimeError):
    """A failure worth showing the user as-is."""


def feed_url(port):
    """The media-source URL for the bot's OBS feed, with a large receive buffer."""
    return f"udp://127.0.0.1:{port}?overrun_nonfatal=1&fifo_size=5000000&buffer_size=4194304"


class OBSControl:
    """A lazily connected, thread-safe obs-websocket client.

    Every method blocks, so call them with `asyncio.to_thread`.
    """

    def __init__(self, host=None, port=None, password=None, scene="Cynthia"):
        """Store the connection settings; nothing connects until first use."""
        self.host = host or DEFAULT_HOST
        self.port = int(port or DEFAULT_PORT)
        self.password = password or ""
        self.scene = scene
        self._client = None
        self._lock = threading.RLock()

    @classmethod
    def from_context(cls, env, config):
        """Build a controller from the dotenv values and the bot config."""
        return cls(
            env.get("OBS_WS_HOST", None),
            env.get("OBS_WS_PORT", None),
            env.get("OBS_WS_PASSWORD", None),
            str(config.get("obs_scene", "Cynthia")),
        )

    def close(self):
        """Drop the connection; the next request reconnects."""
        with self._lock:
            client, self._client = self._client, None
        if client is not None:
            try:
                client.base_client.ws.close()
            except Exception:
                pass

    def call(self, name, *args, **kwargs):
        """Run one obs-websocket request, connecting first when needed."""
        with self._lock:
            if self._client is None:
                try:
                    self._client = obsws.ReqClient(
                        host=self.host,
                        port=self.port,
                        password=self.password,
                        timeout=5,
                    )
                except (OBSSDKError, OSError) as e:
                    raise OBSError(
                        f"Can't reach OBS at {self.host}:{self.port} ({e}). "
                        "Open OBS and enable Tools > WebSocket Server Settings."
                    ) from e
            try:
                return getattr(self._client, name)(*args, **kwargs)
            except OBSSDKRequestError as e:
                if e.code == OUTPUT_RUNNING:
                    raise OBSError(
                        "OBS can't do that while it is streaming or recording."
                    ) from e
                raise OBSError(str(e)) from e
            except (OBSSDKError, OSError) as e:
                self.close()
                raise OBSError(f"Lost the OBS connection: {e}") from e

    @property
    def connected(self):
        """Whether a websocket session is currently open."""
        return self._client is not None

    def status(self):
        """Return what OBS is outputting right now."""
        stream = self.call("get_stream_status")
        record = self.call("get_record_status")
        return {
            "streaming": stream.output_active,
            "reconnecting": stream.output_reconnecting,
            "stream_seconds": stream.output_duration / 1000,
            "congestion": stream.output_congestion,
            "skipped_frames": stream.output_skipped_frames,
            "total_frames": stream.output_total_frames,
            "bytes": stream.output_bytes,
            "recording": record.output_active,
            "paused": record.output_paused,
            "record_seconds": record.output_duration / 1000,
        }

    def canvas(self):
        """Return `(width, height, fps)` of OBS's video settings."""
        v = self.call("get_video_settings")
        return v.base_width, v.base_height, round(v.fps_numerator / v.fps_denominator)

    def set_video(self, height, fps):
        """Make OBS's canvas and output `height` (16:9) at `fps`."""
        width, height = size_for(height)
        self.call("set_video_settings", fps, 1, width, height, width, height)

    def set_stream_key(self, key, bandwidth_test=False, bitrate_kbps=None):
        """Point OBS's stream at Twitch with `key`; optionally as a bandwidth test."""
        if not key:
            raise OBSError("No stream key is set; add TWITCH_STREAM_KEY to .env.")
        settings = dict(TWITCH_SERVICE)
        settings["key"] = key + (BANDWIDTH_TEST_SUFFIX if bandwidth_test else "")
        self.call("set_stream_service_settings", "rtmp_common", settings)
        if bitrate_kbps:
            try:
                # Applies to OBS's Simple output mode
                self.call(
                    "set_profile_parameter",
                    "SimpleOutput",
                    "VBitrate",
                    str(int(bitrate_kbps)),
                )
            except OBSError as e:
                logger.warning("Couldn't set the OBS bitrate: %s", e)

    def start_stream(self):
        """Start OBS's stream output."""
        self.call("start_stream")

    def stop_stream(self):
        """Stop OBS's stream output."""
        self.call("stop_stream")

    def start_record(self):
        """Start OBS recording."""
        self.call("start_record")

    def stop_record(self):
        """Stop OBS recording and return the saved file path (or None)."""
        return getattr(self.call("stop_record"), "output_path", None)

    def screenshot(self, width=1280):
        """Return PNG bytes of what OBS is showing in its program scene."""
        scene = self.call("get_current_program_scene").current_program_scene_name
        canvas_w, canvas_h, _ = self.canvas()
        height = max(1, round(width * canvas_h / canvas_w))
        shot = self.call("get_source_screenshot", scene, "png", width, height, -1)
        return base64.b64decode(shot.image_data.split(",", 1)[1])

    def apply_layout(self, panes, web_port=8000, feed_port=5000):
        """Create, update, and order the scene's sources to match `panes`."""
        scene = self.scene
        scenes = [s["sceneName"] for s in self.call("get_scene_list").scenes]
        if scene not in scenes:
            self.call("create_scene", scene)
        canvas_w, canvas_h, fps = self.canvas()
        inputs = {
            i["inputName"]: i["inputKind"] for i in self.call("get_input_list").inputs
        }
        items = {
            i["sourceName"]: i["sceneItemId"]
            for i in self.call("get_scene_item_list", scene).scene_items
        }
        wanted = set()
        for index, pane in enumerate(panes):
            name = source_name(pane)
            wanted.add(name)
            geo = pane_geometry(pane, (canvas_w, canvas_h))
            if pane["kind"] == "video":
                kind = "ffmpeg_source"
                settings = {
                    "input": feed_url(feed_port),
                    "input_format": "mpegts",
                    "is_local_file": False,
                    "buffering_mb": 2,
                    "clear_on_media_end": False,
                    "close_when_inactive": False,
                    "restart_on_activate": False,
                    "hw_decode": True,
                }
                bounds = "OBS_BOUNDS_SCALE_INNER"
            else:
                kind = "browser_source"
                settings = {
                    "url": pane_url(pane, port=web_port),
                    "width": geo["w"],
                    "height": geo["h"],
                    "fps_custom": True,
                    "fps": fps,
                    "css": pane["css"] or DEFAULT_CSS,
                    "reroute_audio": False,
                    "shutdown": False,
                }
                bounds = "OBS_BOUNDS_STRETCH"
            if name not in inputs:
                created = self.call(
                    "create_input", scene, name, kind, settings, pane["visible"]
                )
                item_id = created.scene_item_id
            else:
                self.call("set_input_settings", name, settings, True)
                if kind == "browser_source":
                    self.call("press_input_properties_button", name, "refreshnocache")
                item_id = items.get(name)
                if item_id is None:
                    item_id = self.call(
                        "create_scene_item", scene, name, pane["visible"]
                    ).scene_item_id
            self.call(
                "set_scene_item_transform",
                scene,
                item_id,
                {
                    "positionX": geo["x"],
                    "positionY": geo["y"],
                    "alignment": 5,
                    "boundsType": bounds,
                    "boundsAlignment": 0,
                    "boundsWidth": geo["w"],
                    "boundsHeight": geo["h"],
                },
            )
            self.call("set_scene_item_enabled", scene, item_id, pane["visible"])
            self.call("set_scene_item_index", scene, item_id, index)
        for name, kind in inputs.items():
            if (
                kind in MANAGED_KINDS
                and (name.startswith(SOURCE_PREFIX) or name == VIDEO_SOURCE)
                and name not in wanted
            ):
                self.call("remove_input", name)
        return len(panes)
