# Shared utilities and services

These modules provide shared behavior used by slash commands, cogs, daemons,
and `Context`. They are not auto-discovered extension modules; import them
through their owning service or helper API instead of creating parallel state.

## Configuration and persistence

| Source | Role |
| --- | --- |
| `cynthia/utils/namespace.py` | Mapping-style `Namespace` used for defaults, config, and shared state. |
| `cynthia/utils/drive.py` | Optional filesystem Drive abstraction. |
| `cynthia/utils/db.py` | Drive-backed SQLite database for logging and message rules. |
| `cynthia/utils/onmessage.py` | Stored message-trigger rules. |
| `cynthia/utils/auth.py` | Permission decorators and authorization helpers. |
| `cynthia/utils/version.py`, `about.py` | Build/version and bot information used by status/help paths. |

Configuration is loaded and persisted by `Context`; see
[configuration](../../configuration.md) before adding defaults or runtime
settings. Drive-backed features are optional when a valid drive path is not
configured. Secrets belong in the working-directory `.env` or local token
files, never on the Drive.

## Integrations and domain behavior

| Source | Role |
| --- | --- |
| `cynthia/utils/nxbt_utils.py` | Controller setup/cleanup, macro parsing and input execution support. |
| `cynthia/utils/cynx.py` | CyNX discovery, authenticated clients, and step protocol. |
| `cynthia/utils/streamcfg.py` | Shared capture/stream configuration and no-signal checks. |
| `cynthia/utils/obs.py`, `obslayout.py` | OBS websocket state and layout helpers. |
| `cynthia/utils/music.py` | Per-guild music manager/player access. |
| `cynthia/utils/twitchapi.py`, `twitchchat.py` | Twitch API and chat clients. |
| `cynthia/utils/encounters.py` | Encounter timing/logging used by Switch hunting. |
| `cynthia/utils/strings.py`, `snowflake.py`, `types.py`, `embeds.py` | Shared formatting, Discord types/IDs, and embed helpers. |
| `cynthia/utils/log.py`, `logger.py` | Logging setup and shared log helpers. |

The local homepage snapshot endpoints are separate from Discord extensions:
`cynthia/site/homepage.py` registers `/api/homepage_status` and
`/api/homepage_thumbnail` on the local stream service. The static homepage and
documentation are maintained by the independent `serenegrace.io` project;
see [documentation publishing](../../operations.md#publishing-the-documentation-site).

## Change and test guidance

Prefer the established manager/service accessor for stateful integrations
(such as `get_manager(client)` for music). Keep authorization at command or
service boundaries, and do not add live credentials to tests. Focused tests
are grouped by behavior: `test_context_storage.py`, `test_core.py`,
`test_frames.py`, `test_cynx.py`, `test_nxbt_macros.py`, `test_streaming.py`,
`test_twitchinfo.py`, `test_music.py`, `test_insights.py`, and
`test_cyclient.py`.
