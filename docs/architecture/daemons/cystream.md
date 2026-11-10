# Local stream and API daemon

**Source:** `cynthia/daemons/cystream.py` — `CYStream`, `create_app`,
`JpegCache`; homepage routes are registered by `cynthia/site/homepage.py`.

## Responsibility

`CYStream` runs the local FastAPI service on `127.0.0.1:8000`. It receives the
shared video/audio rings and serves the browser viewer, MJPEG and audio
streams, overlay panes, WebRTC signaling, and status/statistics APIs. The
`/video_feed` page is rendered from Cynthia's canonical
`cynthia/site/html/video_feed.html`; the viewer template and its required
frontend assets ship with Cynthia, independently of the static `serenegrace.io`
project. The service is loopback-only; a reverse proxy is required for public
HTTP access.

This is not the static documentation site. Documentation is generated from
`docs/**` and served directly by nginx; see
[static site publishing](../../operations.md#publishing-the-documentation-site).

## Data flow and endpoints

The MJPEG encoder idles when there are no viewers and caches JPEGs by frame
hash and output height in a bounded LRU. Each viewer's video can be delayed by
`stream_delay_ms`; a bounded history provides matching delayed inputs and scene
scores. Audio is encoded for each listener from `AudioRing` and catches up to
the live edge rather than replaying stale audio. WebRTC signaling is forwarded
to MediaMTX; the separate [`WebRTCDaemon`](webrtc.md) owns that process/feed.

Status endpoints consume the files written by `StatusCog`; other routes expose
viewer counts, input/scene overlays, stream/audio statistics, Twitch chat, and
StreamElements plain-text values. The narrow homepage API in
`cynthia/site/homepage.py` returns only ribbon status and a no-store JPEG
thumbnail; it does not add a video viewer. Its status uses recent Twitch Helix
state published by `TwitchInfoCog`, and its capture thumbnail is hidden when
frames are stale or the no-signal scene is detected.

## Operations and tests

Keep the API listener bound to loopback. It has no general authentication
layer; proxy only the needed endpoints and apply network/access controls.
Access logs go to the drive as `uvicorn_access.log.gz` when the drive exists.
The `mediamtx` process and WebRTC ports belong to `WebRTCDaemon`, not this
worker.

Route, viewer, status, and homepage behavior is covered by
`tests/test_cystream_api.py` and `tests/test_homepage.py`. Preserve the route
contracts consumed by the static homepage, OBS overlay, StreamElements, and
`cyclient`.
