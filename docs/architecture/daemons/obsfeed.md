# OBS feed daemon

**Source:** `cynthia/daemons/obsfeed.py` — `OBSFeedDaemon`, `Feed`, and
`AudioClock`.

## Responsibility

`OBSFeedDaemon` sends an encoded local UDP feed while OBS is running, or
continuously when `obs_feed: always`. `Feed` supplies FFmpeg with frames from
the shared ring plus PCM from `AudioRing`; FFmpeg produces H.264 MPEG-TS and
AAC for OBS. The feed can use the card's native NV12 frames at 1080p or the
shared BGR frame ring, and applies the configured OBS feed delay before sending
UDP datagrams to localhost.

## Timing and recovery

The daemon polls OBS process presence and configured frame mode, starts/stops
the encoder as demand changes, and retries a failed encoder after a delay.
`AudioClock` smooths drift between capture audio and wall time, inserts silence
across gaps, and avoids large stalls from dragging the video timeline behind.
The feed watchdog allows startup time, then checks two 15-second windows of
fresh-frame throughput; it kills only a slow FFmpeg process, leaving the daemon
to use its retry path. Static game frames still count as healthy when sequence
numbers continue advancing.

The OBS feed needs FFmpeg with NVENC and an NVIDIA-capable host. It normally
targets `udp://127.0.0.1:<obs_feed_port>`. `OBSCog` sets the OBS mode/layout;
`OverlaySyncCog` measures actual OBS video age and adjusts overlay timing, not
this encoder's configured delay.

## Extension and tests

Keep output delay, audio timing, ring claims, and FFmpeg process cleanup
coordinated. The feed copies/releases frame claims before potentially blocking
pipe writes so capture slots remain available. Targeted coverage lives in
`tests/test_streaming.py` and `tests/test_frames.py`.
