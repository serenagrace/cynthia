# Shared frame and audio buffers

**Source:** `cynthia/daemons/frames.py` — `FrameRing`, `FrameClaim`, and
`AudioRing`; dimensions are described by `FB0` in `dman.py`.

`FrameRing` is a three-slot shared-memory ring. A single capture writer
reserves a slot that is not the latest frame and is not held by a reader. On
publication it records sequence number, capture timestamp, and content hash,
then wakes waiters. If every usable slot is claimed, it counts and drops the
new frame rather than overwriting memory a consumer is reading.

Readers call `wait_frame(after_seq, timeout)` and receive a `FrameClaim`.
Release the claim as soon as the needed pixels/metadata are copied; retaining
claims during expensive OCR, encoding, or pipe writes can starve capture. Use
the claim as a context manager where practical.

`AudioRing` is a ten-second shared byte ring for 48 kHz 16-bit stereo PCM.
Readers keep independent positions; a reader that falls too far behind jumps
near the live edge and receives the skipped-byte count. Timestamps let
consumers align audio with frames.

Preserve ring ownership and complete-frame alignment. Tests for slot claims,
writer drops, and audio catch-up live in `tests/test_frames.py`.
