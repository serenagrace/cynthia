# OBS integration cog

**Source:** `cynthia/bot/cogs/obs.py` — `OBSCog`; OBS websocket and layout
helpers are in `cynthia/utils/obs.py` and related utilities.

## Responsibility and state

`OBSCog` polls OBS state on a two-second cadence and publishes whether OBS is
active through the shared daemon state. That signal coordinates video-feed
work and the [OBS feed daemon](../daemons/obsfeed.md). The cog also applies
configured scene/layout behavior, manages stream safeguards, and handles
long-running broadcasts and no-signal conditions.

The cog coordinates OBS and Twitch lifecycle rather than encoding video
itself. Actual capture and FFmpeg output belong to the daemon layer; media
metadata and confirmed Twitch game/hunt values belong to
[`TwitchInfoCog`](twitchinfo.md).

## Extension and tests

Keep websocket polling, state transitions, and safeguards in the cog; keep
encoding/process supervision in daemons. New safeguards must be idempotent
across repeated polls and tolerate OBS being absent or disconnected. Use
`tests/test_streaming.py` for OBS and feed behavior,
and see the [streaming guide](../../streaming.md) for user configuration.
