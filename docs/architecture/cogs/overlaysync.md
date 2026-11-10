# OBS overlay synchronization cog

**Source:** `cynthia/bot/cogs/overlaysync.py` — `OverlaySyncCog`.

## Responsibility and measurement

`OverlaySyncCog` compares sampled capture thumbnails with screenshots of OBS
media output and estimates how far the OBS picture trails capture. It updates
the OBS overlay delay only after multiple consistent, unambiguous estimates;
uncertain matches do not move the delay. This avoids applying an overlay
correction based on one bad sample or a no-signal frame.

It depends on the capture frame stream and OBS media output, but does not own
either: [`UVCDaemon`](../daemons/uvc.md) publishes capture frames and
[`OBSCog`](obs.md) manages OBS state. The resulting delay is consumed by the
OBS layout/overlay path.

## Extension and tests

Keep matching conservative and preserve the existing no-update behavior when
confidence is low. Separate image sampling from the decision to change OBS
settings so matching can be tested without a live OBS instance. Tests belong
in `tests/test_overlaysync.py` and `tests/test_streaming.py`; operator setup
is in the
[streaming guide](../../streaming.md).
