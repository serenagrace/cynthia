# Music cog

**Source:** `cynthia/bot/cogs/music.py` — `MusicCog`; shared queue/player
behavior is in `cynthia/utils/music.py`.

## Responsibility and state

`MusicCog` supplies the Discord voice lifecycle around the shared
`MusicManager`. It checks voice occupancy every 15 seconds and disconnects
when there are no non-bot listeners or when the player has been idle for
30 minutes. The player and queue are managed by the per-guild music manager,
not duplicated in each cog task.

The cog is loaded through the normal recursive cog discovery path. Music
slash commands are registered separately from this event/background-task
module; see the [applications reference](../applications/README.md) and
[Discord feature guide](../../discord-features.md).

## Extension and tests

Put audio/player behavior in `MusicManager` and keep this cog responsible for
voice occupancy and task lifecycle. Ensure unload cancels its periodic task
and does not leave a voice client running. Unit tests for queue/player
utilities are in `tests/test_music.py`; Discord integration checks are
marked `discord_live`.
