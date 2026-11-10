# Audio capture daemon

**Source:** `cynthia/daemons/audio.py` — `AudioDaemon`, `DropoutRepair`.

## Responsibility

`AudioDaemon` captures 48 kHz, 16-bit stereo PCM from the capture card's ALSA
input and writes timestamped chunks to `DMan.audio_ring`. It is independent of
the video frame reader; its consumers are the browser audio stream, OBS feed,
and WebRTC feed.

## Lifecycle and dependencies

The daemon resolves an explicit `AUDIO_DEVICE` value first, then searches
`/proc/asound/cards` for an Elgato card. If no device appears at startup, it
keeps searching. FFmpeg starts only while at least one audio consumer is
active; when all consumers disappear, capture stops and can start again later.
An FFmpeg exit or a three-second read stall causes a retry after two seconds.

`DropoutRepair` buffers a short tail so it can identify the Elgato USB audio
dropout pattern across FFmpeg pipe-read boundaries. It repairs a packet only
when the zero-frame run and surrounding signal meet its checks; ordinary quiet
audio is not automatically treated as corruption. The repaired stream is
written as whole stereo frames to the shared ring.

## Extension points and tests

Keep ALSA/FFmpeg process ownership in the worker loop. Audio buffers are
consumed by `OBSFeedDaemon`, `WebRTCDaemon`, and `CYStream`; preserve capture
timestamps and whole-frame alignment when changing reads or buffering. Test
dropout repair and subprocess retry behavior in `tests/test_streaming.py` and
`tests/test_frames.py`.
