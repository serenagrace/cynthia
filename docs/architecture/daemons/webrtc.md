# WebRTC daemon

**Source:** `cynthia/daemons/webrtc.py` — `WebRTCDaemon`; encoded output uses
the reusable `Feed` implementation in `obsfeed.py`.

## Responsibility and demand

`WebRTCDaemon` starts a local MediaMTX process only when WebRTC is enabled and
the `mediamtx` executable is available. It configures MediaMTX to serve the
single `cynthia` path over WebRTC, with the local ingest, web, media, and API
ports supplied by configuration. The MediaMTX API is bound to loopback.

The daemon polls WebRTC session readers and the web app's recent signaling
request. It creates the FFmpeg `Feed` only while a viewer is present or a
browser recently requested a session, and keeps that feed for at most the
20-second request grace. Frame rate, height, native-frame availability, and
bitrate are read from shared settings. Audio is encoded as Opus for WebRTC.

## Lifecycle and safe extension

The web feed yields to controller and OBS work. On exit, the daemon stops
`Feed`, terminates MediaMTX, removes its temporary config directory, and
clears shared readiness/viewer state. If MediaMTX exits unexpectedly it is
retried after a backoff; if it is missing, WebRTC remains disabled while the
MJPEG path remains available.

Keep public advertised hosts separate from the local MediaMTX API address,
avoid opening the feed without demand, and release encoder/process resources
on every restart path. The WebRTC feed shares `Feed` timing and watchdog
behavior with OBS. See `tests/test_streaming.py` and the WebRTC-related cases
in `tests/test_cystream_api.py`.
