"""Default environment, bot configuration, context, and permission values."""


class Defaults:
    """Container for default configuration and permission mappings."""

    env = {
        "DISCORD_BOT_TOKEN": None,
        "OTP_SECRET": None,
        "DRIVE_PATH": None,
        "ELGATO_USB_ID": None,
        "SYNC_GUILD_ID": None,
        "STATUS_HOSTS": None,
        "YTDL_COOKIES_FILE": None,
        # obs-websocket (OBS 28+): Tools > WebSocket Server Settings
        "OBS_WS_HOST": None,
        "OBS_WS_PORT": None,
        "OBS_WS_PASSWORD": None,
        # Stream key OBS uses; TWITCH_STREAM_KEY takes precedence for /twitch
        "OBS_STREAM_KEY": None,
        "TWITCH_STREAM_KEY": None,
        # Channel name for /twitchurl and the chat overlay
        "TWITCH_CHANNEL": None,
        # Twitch app credentials (dev.twitch.tv) for setting the title and category
        "TWITCH_CLIENT_ID": None,
        "TWITCH_CLIENT_SECRET": None,
    }
    config = {
        "silent": False,
        "debug": False,
        "owner": None,
        # restart the looping macro 5s after an encounter
        "encounter_reset": True,
        # systemd units checked by the /status command
        "status_services": ["cynthia.service"],
        # send the video feed to OBS (over UDP) while OBS is running
        # True follows OBS, "always" feeds regardless, False disables
        "obs_feed": True,
        "obs_feed_port": 5000,
        "obs_feed_bitrate": "50M",
        # frame rate (15, 24, 30, 60) and height (480, 720, 1080) of each endpoint;
        # change them live with /webstream and /obs. CV is always capped at 30 fps.
        "web_fps": 30,
        "web_height": 720,
        "obs_fps": 60,
        "obs_height": 1080,
        # OBS scene the bot manages, and the YAML file describing its panes
        "obs_scene": "Cynthia",
        "obs_layout_file": "obs_layout.yaml",
        # Twitch video bitrate (kbps) applied to OBS when streaming from Discord
        "twitch_bitrate_kbps": 6000,
        # restart a stream this long (hours) before Twitch ends it at 48; 0 disables
        "twitch_restart_hours": 24,
        # stop a stream that shows the capture card's no-signal screen this long; 0 disables
        "twitch_no_signal_stop_minutes": 10,
        # clip the stream when a shiny is found (needs /twitch auth)
        "twitch_auto_clip": True,
        # seconds after the shiny reaches the input visualizer (OBS delay) to clip
        "twitch_clip_delay_seconds": 10,
        # set the Twitch title/category from the detected game and hunt
        "twitch_auto_info": True,
        # how long a new game or hunt must hold before the channel is changed
        "twitch_info_confirm_seconds": 60,
        # detected game title -> Twitch category name or id, when they differ
        "twitch_categories": {},
        # serve the web viewer over WebRTC (needs the `mediamtx` binary); the page
        # falls back to MJPEG. Media flows over UDP and TCP `webrtc_media_port`;
        # list public IPs or hostnames in `webrtc_hosts` for viewers off the LAN
        "webrtc": True,
        "webrtc_port": 8889,
        "webrtc_media_port": 8189,
        "webrtc_api_port": 9997,
        "webrtc_ingest_port": 5100,
        "webrtc_bitrate": "8M",
        "webrtc_hosts": [],
        # hold the OBS feed back this long (0 = send immediately)
        "obs_feed_delay_ms": 1000,
        # extra lag for OBS overlay inputs/SSIM, covering encode, OBS buffer and decode
        "obs_overlay_lag_ms": 1700,
        # hold the web stream's video back this long so audio can buffer smoothly
        "stream_delay_ms": 1000,
    }
    context = {}
    perms = {
        "privileged": [],
        "nxbt": [],
        "drive": [],
        "owners": [],
        "admins": [],
        "allowed_commands": [],
    }
