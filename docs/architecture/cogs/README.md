# Discord cogs

Cogs are event-driven Discord extensions in `cynthia/bot/cogs/`. `Bot` walks
this tree recursively, imports each module except package/underscore files,
and calls its `async def setup(bot)` function. A cog's `cog_load`/`cog_unload`
hooks own its background tasks and listeners; unload should cancel and await
tasks so reload and bot shutdown do not leave duplicate workers.

The seven discovered cog modules are listed below. Command registration is
separate: slash-command modules live in
[`applications/`](../applications/README.md). Shared command and cog
conventions are in the [development guide](../../development.md).

| Module / cog | Responsibility |
| --- | --- |
| [`bouncer.py` — `BouncerCog`](bouncer.md) | Member screening and moderation decisions. |
| [`llmchat.py` — `LLMChatCog`](llmchat.md) | Queued Twitch chat, model, memory, and voice integration. |
| [`music.py` — `MusicCog`](music.md) | Discord voice-player housekeeping. |
| [`obs.py` — `OBSCog`](obs.md) | OBS state, safeguards, layouts, and stream lifecycle. |
| [`overlaysync.py` — `OverlaySyncCog`](overlaysync.md) | Capture-to-OBS delay measurement for overlays. |
| [`status.py` — `StatusCog`](status.md) | Presence, drive status files, and owner alerts. |
| [`twitchinfo.py` — `TwitchInfoCog`](twitchinfo.md) | Confirmed Twitch game/hunt metadata and live status. |

When adding a cog, keep one owner for each long-running task, cancel it during
unload, and use `interaction.client`/`bot` services instead of constructing
parallel database, stream, or controller clients. Add behavior-level tests in
`tests/` rather than importing a cog solely to assert its class exists.
