"""Serve the live capture to browsers over WebRTC through a local MediaMTX."""

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from cynthia.utils.log import get_logger
from cynthia.utils.streamcfg import setting

from .daemon import Daemon
from .obsfeed import Feed

WEB_NICE = 15
logger = get_logger(__name__, logging.INFO)

PATH_NAME = "cynthia"
POLL_SECONDS = 1.0
# The feed keeps running this long after the last page asked for WebRTC
IDLE_SECONDS = 20
MEDIAMTX_RETRY_SECONDS = 10


def mediamtx_config(ingest_port, http_port, udp_port, api_port, hosts=()):
    """Return MediaMTX settings that read our MPEG-TS feed and serve only WebRTC."""
    lines = [
        "logLevel: warn",
        "rtsp: false",
        "rtmp: false",
        "hls: false",
        "srt: false",
        "moq: false",
        # The default socket buffer overflows when a keyframe arrives in one burst
        "udpReadBufferSize: 4194304",
        "api: true",
        f"apiAddress: 127.0.0.1:{api_port}",
        "webrtc: true",
        f"webrtcAddress: 127.0.0.1:{http_port}",
        f"webrtcLocalUDPAddress: :{udp_port}",
        f"webrtcLocalTCPAddress: :{udp_port}",
        "webrtcAdditionalHosts: " + json.dumps(list(hosts)),
        "paths:",
        f"  {PATH_NAME}:",
        f"    source: udp+mpegts://127.0.0.1:{ingest_port}",
    ]
    return "\n".join(lines) + "\n"


def count_readers(api_port):
    """Return how many WebRTC sessions are playing, or None if the API is down."""
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{api_port}/v3/webrtcsessions/list", timeout=1
        ) as res:
            items = json.load(res).get("items", [])
    except (OSError, ValueError):
        return None
    return sum(1 for item in items if item.get("state") == "read")


class WebRTCDaemon(Daemon):
    """Encode the frame ring once with NVENC and let MediaMTX fan it out."""

    def __init__(self, dman):
        """Read the WebRTC settings and start the daemon process."""
        config = dman.context.config

        def loop(
            ns,
            uns,
            ring,
            audio_ring,
            native_ring,
            enabled,
            http_port,
            udp_port,
            api_port,
            ingest_port,
            bitrate,
            delay_ms,
            hosts,
        ):
            """Run MediaMTX and feed it while a page wants WebRTC."""
            # The web view is an afterthought: it yields to NXBT, to OBS and to
            # the OBS feed. MediaMTX and the encoder inherit this priority.
            os.nice(WEB_NICE)
            uns.webrtc_ready = False
            uns.webrtc_port = http_port
            uns.webrtc_viewers = 0
            uns.webrtc_feeding = False
            binary = shutil.which("mediamtx")
            if not enabled or binary is None:
                if enabled:
                    logger.warning("`mediamtx` isn't installed; WebRTC is disabled.")
                return
            workdir = tempfile.mkdtemp(prefix="cynthia-mediamtx-")
            config_path = Path(workdir) / "mediamtx.yml"
            config_path.write_text(
                mediamtx_config(ingest_port, http_port, udp_port, api_port, hosts)
            )
            server = None
            feed = None
            feed_mode_now = None
            last_seq = 0
            last_sent_ns = 0
            next_poll = 0.0
            retry_at = 0.0
            try:
                while ns.run:
                    now = time.monotonic()
                    if server is not None and server.poll() is not None:
                        logger.warning("MediaMTX exited; restarting it shortly.")
                        server = None
                        uns.webrtc_ready = False
                        retry_at = now + MEDIAMTX_RETRY_SECONDS
                    if server is None and now >= retry_at:
                        server = subprocess.Popen(
                            [binary, str(config_path)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        uns.webrtc_ready = True
                        logger.notice("WebRTC is served on port %s", http_port)
                    if now >= next_poll:
                        next_poll = now + POLL_SECONDS
                        readers = count_readers(api_port) if server else None
                        uns.webrtc_viewers = readers or 0
                    asked = getattr(uns, "webrtc_requested", 0.0)
                    wanted = server is not None and (
                        uns.webrtc_viewers > 0 or time.time() - asked < IDLE_SECONDS
                    )
                    native = bool(getattr(uns, "capture_native", False))
                    requested = (
                        setting(uns, "web_fps"),
                        setting(uns, "web_height"),
                        native,
                    )
                    if feed is not None and (not wanted or requested != feed_mode_now):
                        feed.stop()
                        feed = None
                        uns.webrtc_feeding = False
                    if wanted and feed is None:
                        feed_mode_now = requested
                        last_seq = 0  # each ring counts its own frames
                        last_sent_ns = 0
                        fps, height, native = requested
                        feed = Feed(
                            ingest_port,
                            fps,
                            bitrate,
                            audio_ring,
                            delay_ms,
                            height,
                            audio_codec="opus",
                            gop_seconds=1,
                            vbv_seconds=0.25,
                            native=native,
                            source_ring=native_ring if native else ring,
                        )
                        uns.webrtc_feeding = True
                        logger.info("WebRTC feed started at %sp%s", height, fps)
                    if feed is None:
                        time.sleep(0.25)
                        continue
                    if feed.proc.poll() is not None:
                        logger.warning(
                            "WebRTC encoder exited: %s",
                            feed.proc.stderr.read().decode(errors="replace").strip(),
                        )
                        feed.stop()
                        feed = None
                        uns.webrtc_feeding = False
                        uns.webrtc_requested = 0.0
                        time.sleep(1)
                        continue
                    claim = (native_ring if feed_mode_now[2] else ring).wait_frame(
                        last_seq, 0.25
                    )
                    if claim is None:
                        continue
                    last_seq = claim.seq
                    try:
                        if claim.time_ns - last_sent_ns >= 0.8e9 / feed_mode_now[0]:
                            last_sent_ns = claim.time_ns
                            feed.write_claim(claim)
                    finally:
                        claim.release()
            finally:
                if feed is not None:
                    feed.stop()
                uns.webrtc_feeding = False
                if server is not None:
                    server.terminate()
                    try:
                        server.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        server.kill()
                shutil.rmtree(workdir, ignore_errors=True)
                uns.webrtc_ready = False

        hosts = config.get("webrtc_hosts", [])
        super().__init__(
            dman,
            bool(config.get("webrtc", True)),
            int(config.get("webrtc_port", 8889)),
            int(config.get("webrtc_media_port", 8189)),
            int(config.get("webrtc_api_port", 9997)),
            int(config.get("webrtc_ingest_port", 5100)),
            str(config.get("webrtc_bitrate", "8M")),
            max(0, int(config.get("stream_delay_ms", 1000))),
            [hosts] if isinstance(hosts, str) else list(hosts or []),
            ring=True,
            audio_ring=True,
            native_ring=True,
        )
        self.loop = loop
        self.start()
