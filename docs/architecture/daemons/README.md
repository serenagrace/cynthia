# Daemons

## What belongs here

Daemon subclasses are process workers below `cynthia/daemons/`. At bot startup,
`DMan` scans direct Python modules in this directory, imports them, finds
subclasses of `Daemon`, and constructs all discovered classes. Daemon behavior
is therefore opt-out/configuration-driven rather than a manual registration
list.

Each daemon owns a process and namespace. The manager sets its `ns.run` flag
false during shutdown; workers must finish their own I/O cleanup and mark
`ns.done` where required. `Daemon` carries shared rings into workers and
supports snapshots for restartable workers.

## Discovered daemon modules

| Module / class | Responsibility |
| --- | --- |
| [`uvc.py` — `UVCDaemon`](uvc.md) | Capture frames from the USB video device. |
| [`cv.py` — `CVDaemon`](cv.md) | Score scenes, OCR home-screen titles, and publish hunt state. |
| [`audio.py` — `AudioDaemon`](audio.md) | Capture and repair game audio into the shared audio ring. |
| [`obsfeed.py` — `OBSFeedDaemon`](obsfeed.md) | Encode the local OBS feed and keep audio aligned. |
| [`webrtc.py` — `WebRTCDaemon`](webrtc.md) | Run demand-driven WebRTC output through MediaMTX. |
| [`cystream.py` — `CYStream`](cystream.md) | Serve local video, audio, overlays, and status APIs. |
| [`nxbt.py` — `NXBTDaemon`](nxbt.md) | Own the selected controller backend and macro playback. |
| [`cypi.py` — `CyPiDaemon`](cypi.md) | Discover and manage the wired CyPi network session. |

`dman.py`, `daemon.py`, and `frames.py` are support modules rather than
discovered daemon subclasses. They are documented separately because changes
there affect every worker.

## Shared infrastructure pages

Read about the [daemon process base](daemon-base.md),
[manager](manager.md), and [shared frame and audio buffers](frame-buffers.md)
before changing process lifecycle or shared data.

## Extending a daemon

Use the base class and manager conventions rather than creating unmanaged
processes. Pass only needed rings/arguments to `Daemon`, check the process
namespace's `run` flag in worker loops, close sockets/processes/threads on
shutdown, and use the shared `uns` namespace or queues for cross-process
communication. Avoid treating a daemon manager proxy as a substitute for
thread-safe ownership of sockets.

Add configuration defaults in `cynthia/context/defaults.py`, expose runtime
changes through the appropriate service/command, and document the setting in
the feature guide. Add a focused test in `tests/`; process discovery and
shutdown tests live in `tests/test_dman.py`, controller protocols in
`tests/test_cypi.py` / `tests/test_nxbt_macros.py`, frame synchronization in
`tests/test_frames.py`, and capture/stream behavior in `tests/test_cv_scenes.py`
and `tests/test_streaming.py`.
