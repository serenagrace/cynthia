# USB capture daemon

**Source:** `cynthia/daemons/uvc.py` — `UVCDaemon` supervises the `UVC` reader.

## Responsibility

`UVCDaemon` opens the USB video capture device, selects a mode suitable for
active consumers, and publishes timestamped frames to `FrameRing`. It also
publishes raw NV12 frames to the native ring when the card supplies usable
1080p NV12; otherwise it captures YUYV/BGR and provides the ordinary ring.
Downstream consumers are CV, the web stream, OBS, WebRTC, and the homepage
thumbnail.

The capture mode follows `capture_mode(uns)`, which considers which stream
consumers are active. A higher requested mode is applied immediately; a
cheaper mode must remain requested for ten seconds before the card is reopened
at the lower mode. Failed frame reads end the capture attempt so the supervisor
can reopen the device.

## Device setup and recovery

If `ELGATO_USB_ID` is set, startup calls `usbreset` before opening the device.
OpenCV is asked for the selected 16:9 size and frame rate; `describe()` reports
what the device actually returns. Frame hashes support freeze detection in
`DMan`; they are not a claim that the image contains new game content. The
manager restarts this daemon after a stall, while its separate freeze watcher
resets a card that keeps delivering an unchanged picture.

## Extension and tests

Keep device I/O inside `UVC` and supervise it from `UVCDaemon`. Publish complete
frames with capture timestamps and release shared-ring claims promptly. Device
format, mode selection, and capture recovery are exercised in
`tests/test_streaming.py`, `tests/test_cv_scenes.py`, and `tests/test_frames.py`.
