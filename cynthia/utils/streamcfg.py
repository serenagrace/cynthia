"""Frame rate and resolution settings for the web stream, OBS, and the capture card.

The settings live in the daemon manager's shared namespace (`uns`) so a Discord
command can change them while the daemons run. The capture card always runs at
the cheapest mode that satisfies every endpoint that is actually running.
"""

# Output heights (width follows at 16:9) that either stream may select
RESOLUTIONS = {480: (854, 480), 720: (1280, 720), 1080: (1920, 1080)}
FPS_CHOICES = (15, 24, 30, 60)

DEFAULT_WEB_FPS = 30
DEFAULT_WEB_HEIGHT = 720
DEFAULT_OBS_FPS = 60
DEFAULT_OBS_HEIGHT = 1080

# CV and OCR never run faster than this, whatever the streams are set to
CV_FPS = 30
# Scenes and OCR need at least this much capture resolution
CV_MIN_HEIGHT = 720
# The capture card is only ever driven at one of these rates
CAPTURE_FPS_CHOICES = (30, 60)


def parse_height(value):
    """Return a supported output height for `value` such as 720 or "720p"."""
    try:
        height = int(str(value).strip().lower().rstrip("p"))
    except ValueError:
        raise ValueError(f"Resolution must be one of {height_names()}.") from None
    if height not in RESOLUTIONS:
        raise ValueError(f"Resolution must be one of {height_names()}.")
    return height


def parse_fps(value):
    """Return a supported frame rate for `value` such as 30 or "60fps"."""
    try:
        fps = int(str(value).strip().lower().removesuffix("fps"))
    except ValueError:
        raise ValueError(f"Frame rate must be one of {fps_names()}.") from None
    if fps not in FPS_CHOICES:
        raise ValueError(f"Frame rate must be one of {fps_names()}.")
    return fps


def height_names():
    """Human-readable list of the selectable resolutions."""
    return ", ".join(f"{h}p" for h in RESOLUTIONS)


def fps_names():
    """Human-readable list of the selectable frame rates."""
    return ", ".join(str(f) for f in FPS_CHOICES)


def size_for(height):
    """Return `(width, height)` for a selectable output height."""
    return RESOLUTIONS[height]


def init_settings(uns, config):
    """Seed the shared namespace from the config, ignoring invalid values."""
    for key, parse, default in (
        ("web_fps", parse_fps, DEFAULT_WEB_FPS),
        ("web_height", parse_height, DEFAULT_WEB_HEIGHT),
        ("obs_fps", parse_fps, DEFAULT_OBS_FPS),
        ("obs_height", parse_height, DEFAULT_OBS_HEIGHT),
    ):
        try:
            value = parse(config.get(key, default))
        except ValueError:
            value = default
        setattr(uns, key, value)
    uns.web_viewers = 0
    uns.obs_active = False


def setting(uns, key):
    """Read one of the four stream settings from the shared namespace."""
    defaults = {
        "web_fps": DEFAULT_WEB_FPS,
        "web_height": DEFAULT_WEB_HEIGHT,
        "obs_fps": DEFAULT_OBS_FPS,
        "obs_height": DEFAULT_OBS_HEIGHT,
    }
    return getattr(uns, key, defaults[key])


def capture_mode(uns):
    """Return the `(height, fps)` the capture card should run at right now.

    Only endpoints that are running count: the web stream needs a viewer, and
    OBS needs to be recording or streaming. The card never exceeds the highest
    running request, but it never drops below what CV needs either.
    """
    heights = [CV_MIN_HEIGHT]
    fps = [CV_FPS]
    obs_active = getattr(uns, "obs_active", False)
    # OBS outranks the web view, so viewers never raise the card's mode over it
    web_viewers = getattr(uns, "web_viewers", 0) + getattr(uns, "webrtc_viewers", 0)
    if web_viewers > 0 and not obs_active:
        heights.append(setting(uns, "web_height"))
        fps.append(setting(uns, "web_fps"))
    if obs_active:
        heights.append(setting(uns, "obs_height"))
        fps.append(setting(uns, "obs_fps"))
    capture_fps = 60 if max(fps) > 30 else 30
    # The Elgato 4K X offers 30 fps only at 1080p and 480p; 720p starts at 50 fps
    height = max(heights)
    if capture_fps == 30 and height > 480:
        height = 1080
    return height, capture_fps
