"""The OBS scene layout: which panes appear on stream and where.

The layout is a YAML file. Positions and sizes are fractions of the OBS canvas
(0 to 1), so one layout works at any resolution. Panes are stacked in file
order, later ones on top. `kind` picks what the pane shows:

* `video`   the capture feed (the UDP media source)
* `status`, `inputs`, `ssim`, `stats`, `chat`, `watermark`   pages served by the bot
* `url`     any web page, given by `url`
"""

import logging
import time
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

KINDS = ("video", "status", "inputs", "ssim", "stats", "chat", "watermark", "url")
SOURCE_PREFIX = "Cynthia "
VIDEO_SOURCE = "Cynthia Feed"
OBS_SYNC_MAX_DELAY_MS = 10000
OBS_SYNC_TTL_SECONDS = 30
DEFAULT_CSS = (
    "body { background-color: rgba(0, 0, 0, 0); margin: 0; overflow: hidden; }"
)

DEFAULT_LAYOUT = {
    "panes": [
        {"name": "video", "kind": "video", "x": 0, "y": 0, "w": 1, "h": 1},
        {
            "name": "inputs",
            "kind": "inputs",
            "x": 0.785,
            "y": 0.34,
            "w": 0.2,
            "h": 0.22,
        },
        {"name": "chat", "kind": "chat", "x": 0.015, "y": 0.5, "w": 0.23, "h": 0.48},
        {"name": "ssim", "kind": "ssim", "x": 0.015, "y": 0.02, "w": 0.23, "h": 0.3},
        {"name": "stats", "kind": "stats", "x": 0.69, "y": 0.68, "w": 0.3, "h": 0.32},
        {
            "name": "watermark",
            "kind": "watermark",
            "x": 0.8,
            "y": 0.965,
            "w": 0.2,
            "h": 0.035,
        },
    ]
}


class LayoutError(ValueError):
    """Raised when the layout file is malformed."""


def overlay_delay_ms(uns, fallback):
    """Use a fresh measured OBS delay, or the configured delay if its cog is unavailable."""
    sync = getattr(uns, "obs_overlay_sync", None)
    if (
        sync
        and 0 <= time.monotonic() - sync["at"] <= OBS_SYNC_TTL_SECONDS
        and 0 <= sync["delay_ms"] <= OBS_SYNC_MAX_DELAY_MS
    ):
        return sync["delay_ms"]
    return fallback


def source_name(pane):
    """The OBS source name for a pane; the video keeps the imported name."""
    return VIDEO_SOURCE if pane["kind"] == "video" else SOURCE_PREFIX + pane["name"]


def _fraction(pane, key, default):
    """Read a 0-1 number from a pane, rejecting anything else."""
    value = pane.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LayoutError(f"Pane `{pane.get('name')}`: `{key}` must be a number.")
    if not 0 <= value <= 1:
        raise LayoutError(f"Pane `{pane.get('name')}`: `{key}` must be 0 to 1.")
    return float(value)


def normalize(layout):
    """Validate a parsed layout and return its panes with every field filled in."""
    if not isinstance(layout, dict) or not isinstance(layout.get("panes"), list):
        raise LayoutError("The layout needs a `panes` list.")
    panes, seen = [], set()
    for raw in layout["panes"]:
        if not isinstance(raw, dict) or not raw.get("name"):
            raise LayoutError("Every pane needs a `name`.")
        kind = raw.get("kind", raw["name"])
        if kind not in KINDS:
            raise LayoutError(
                f"Pane `{raw['name']}`: unknown kind `{kind}` (use {', '.join(KINDS)})."
            )
        name = str(raw["name"])
        if name in seen:
            raise LayoutError(f"Duplicate pane name `{name}`.")
        seen.add(name)
        pane = {
            "name": name,
            "kind": kind,
            "x": _fraction(raw, "x", 0),
            "y": _fraction(raw, "y", 0),
            "w": _fraction(raw, "w", 1),
            "h": _fraction(raw, "h", 1),
            "visible": bool(raw.get("visible", True)),
            "url": raw.get("url"),
            "css": raw.get("css"),
        }
        if kind == "url" and not pane["url"]:
            raise LayoutError(f"Pane `{name}` of kind `url` needs a `url`.")
        panes.append(pane)
    if sum(p["kind"] == "video" for p in panes) > 1:
        raise LayoutError("Only one `video` pane is allowed.")
    return panes


def load_layout(path):
    """Load the layout file, falling back to the built-in layout when absent."""
    path = Path(path)
    if not path.is_file():
        return normalize(DEFAULT_LAYOUT)
    try:
        return normalize(yaml.safe_load(path.read_text()))
    except yaml.YAMLError as e:
        raise LayoutError(f"{path.name} is not valid YAML: {e}") from e


def pane_url(pane, host="127.0.0.1", port=8000):
    """The page a browser-source pane shows."""
    if pane["kind"] == "url":
        return pane["url"]
    return f"http://{host}:{port}/pane/{pane['kind']}"


def pane_geometry(pane, canvas):
    """Pixel position and size of a pane on a `(width, height)` canvas."""
    width, height = canvas
    return {
        "x": round(pane["x"] * width),
        "y": round(pane["y"] * height),
        "w": max(1, round(pane["w"] * width)),
        "h": max(1, round(pane["h"] * height)),
    }
