# Twitch metadata cog

**Source:** `cynthia/bot/cogs/twitchinfo.py` — `TwitchInfoCog`; API access is
provided by shared Twitch utilities.

## Responsibility and update policy

`TwitchInfoCog` checks the current game/hunt context about every five seconds,
but applies Twitch metadata only after the candidate has remained confirmed.
It persists the last applied state to avoid needless repeated updates. The
game-title mapping is a maintained list, not an exhaustive external game
catalog; the current Switch home-screen OCR title behavior is described in the
[CV daemon reference](../daemons/cv.md).

Separately, it publishes recent authorized Twitch Helix live-state checks for
the static homepage ribbon about every 30 seconds. This is Twitch channel
status, not an inference from OBS being open. The homepage API may therefore
show live status while OBS is not in use. Thumbnail visibility is decided by
recent capture freshness and no-signal detection in the web/API path.

Shiny clipping waits for overlay delay so the saved clip includes the intended
moment. That action has its own stream/OBS checks; do not conflate it with the
Helix-based homepage live flag.

## Extension and tests

Keep API polling rate-limited and apply only stable values. If changing the
persisted format, preserve compatibility with the last-applied state file.
Test title confirmation, persistence, and homepage live publication in
`tests/test_twitchinfo.py` and `tests/test_homepage.py`. See the
[Twitch/streaming guide](../../streaming.md) for operator behavior.
