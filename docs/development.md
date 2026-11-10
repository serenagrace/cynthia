# Development and integrations

This guide covers the code layout, supported extension points, local checks,
the HTTP service, and the optional `cyclient` utility. It is not a user-facing
command catalog; see the [feature guides](README.md#feature-guides).

## Architecture

`cynthia.__main__` parses command-line options, builds a `Context`, starts the
Discord `Bot`, and persists configuration and permissions during shutdown.
`Context` owns the loaders for configuration, permissions, environment, and
application metadata.

The `Bot` is the integration root. It creates:

- The Discord command tree, messenger, and cog loader.
- A `Drive` abstraction and SQLite database for logging and message rules.
- A `DMan` daemon manager that provides shared video/audio frame buffers and
  starts discovered daemon processes.
- Health monitoring and cleanup handlers.

The capture pipeline and integrations are daemons, including UVC capture, CV,
OBS/video streaming, Bluetooth control, and optional CyNX communication.
Daemons communicate through shared buffers/namespaces and must stop when their
manager namespace's `run` flag is cleared. `Bot.close()` signals daemons and
waits for cleanup.

## Extension conventions

### Slash commands

Add a direct `.py` module under `cynthia/bot/applications/`. `CommandTree`
discovers these modules except `__init__.py` and `tree.py`, imports each, and
registers its `__application__` value. That value may be one command, an
iterable of commands, or an application class. Application classes receive
the bot client, may implement `async __ainit__`, and provide `apps()`.

Use the shared client services from an interaction:

```python
interaction.client.config
interaction.client.perms_check
interaction.client.drive
interaction.client.database
interaction.client.dman
interaction.client.verify
```

Apply the existing checks in `cynthia.utils.auth` and/or
`interaction.client.perms_check` for authorization. Do not rely only on
Discord's default command permissions: runtime permission checks are also
needed for protected bot operations.

### Cogs

A cog module must expose `async def setup(bot)` and register its cog there.
Cynthia searches recursively below `cynthia/bot/cogs/`; nested modules are
supported. Prefer cogs for Discord listeners and event-driven behavior that
does not belong in a slash-command module.

### Daemons

Put a `Daemon` subclass in a direct module under `cynthia/daemons/`. The
manager discovers direct `.py` modules and starts each discovered daemon
during bot construction. A daemon should use the manager's namespace and
respect its `run` flag, release shared resources, and honor stop/close
lifecycle methods so `Bot.close()` can shut it down. Add configuration
defaults through `cynthia/context/defaults.py` and document any public setting
in the appropriate guide and example configuration.

## Tests and formatting

The package requires Python 3.11. Install development tools with the `dev`
extra (included in the quick start) and run:

```bash
python -m pytest -m "not discord_live"
bin/black.sh
```

The live Discord tests are opt-in and target a configured test bot; they are
excluded by the command above. `bin/black.sh` runs the repository's configured
isort and Black formatting. Keep tests focused on changed behavior and do not
run commands that modify the user's runtime configuration or live Discord
server as part of routine local tests.

## HTTP API and StreamElements

The CYStream daemon serves a local FastAPI application at
`http://127.0.0.1:8000`. It serves the video viewer and JSON/stream endpoints.
The listener is bound to loopback; a reverse proxy is needed for remote access.
The application does not provide API authentication, so proxy only the
specific resources needed and use suitable access controls. Do not expose
controller actions or private status data to an untrusted network.

While the bot is running, FastAPI's generated schema is available locally at
`http://127.0.0.1:8000/openapi.json`; its interactive docs are at
`http://127.0.0.1:8000/docs`. These are local development/inspection
interfaces and should not be made public without an explicit need and proxy
policy.

Useful endpoint groups include:

| Endpoint | Purpose |
| --- | --- |
| `/video_feed` | Browser video viewer. |
| `/api/stream_endpoint` | MJPEG video stream. |
| `/api/webrtc`, `/api/whep` | WebRTC signaling integration. |
| `/api/audio_stream`, `/api/audio_stats` | Capture audio and listener statistics. |
| `/api/user_status`, `/api/activity_stats` | Status and activity data used by clients. |
| `/api/viewers` | Current viewer count. |
| `/api/homepage_status` | Narrow status data used by the public homepage ribbon. |
| `/api/homepage_thumbnail` | Current ribbon thumbnail as a no-store JPEG response. |
| `/api/inputs`, `/api/ssim_data` | Controller inputs and scene-match scores; delayed versions can match a video feed. |
| `/api/sync`, `/api/stream_stats` | Video latency, capture, and stream statistics. |
| `/api/twitch_chat` | Public overlay chat-pane data. |
| `/pane/{kind}` | HTML overlay pane. |

The following plain-text endpoints can be used in StreamElements custom API
commands:

| Endpoint | Response |
| --- | --- |
| `/api/streamelements/uptime` | Bot process uptime. |
| `/api/streamelements/online` | `True` while the endpoint responds. |
| `/api/streamelements/description` | Current hunt description, custom status, or an idle message. |

Example custom command text:

```text
Cynthia ${customapi.https://example.com/api/streamelements/description}
```

Replace the example host with a secured reverse-proxy URL. Allow only the
required paths in the proxy, and review the public data returned by every
enabled endpoint. The homepage only needs `/api/homepage_status` and
`/api/homepage_thumbnail` for its ribbon; keep that interface narrow. The
status endpoint checks whether Twitch is live through the authorized Helix
integration; it does not infer a live broadcast from OBS. The thumbnail
prefers Twitch's live thumbnail, otherwise uses the CYStream capture, and is
hidden when that capture is stale or shows the Elgato no-signal image. Its
response is a no-store JPEG. The running bot must be restarted to serve these
new routes. MCP integration in this repository is limited to the read-only
`/api/user_status` and `/api/viewers` endpoints.

## Home-screen game-title OCR

The CV daemon reads selected game titles from the Switch home screen against a
maintained catalog, not an exhaustive external game database. The catalog
includes existing Pokémon titles and Nintendo Classics systems such as SNES,
NES, Nintendo 64, Game Boy, Game Boy Advance, SEGA Genesis/Mega Drive, and
Nintendo GameCube.

OCR cleanup strips `Nintendo Classics` and `Nintendo Switch Online` branding.
It can resolve distinctive fragments when a title scrolls or wraps; ambiguous
fragments and unknown text are retained rather than forced into a guessed game
name. For example, `Super Nintendo Entertainment System–Nintendo Classics`
resolves to `Super Nintendo Entertainment System`. A known title remains
stable across compatible OCR fragments, and a different known selection must
remain visible for 0.8 seconds before it replaces the current title.

This identifies a selected title; it does not imply game-specific state or
encounter detection. Only implemented scenes and hunt workflows support those
features.

## Discord Rich Presence client

`tools/cyclient.py` polls the bot's `/api/user_status` endpoint and publishes
the detected game and hunt through the Discord desktop app's Rich Presence.
The bot must be running, and the desktop host must be able to reach it.

Install the optional dependencies:

```bash
python -m pip install -e ".[cyclient]"
```

That extra adds `pypresence` and `requests`, but installing the project also
installs the full bot and enforces Python 3.11. On a separate desktop, install
only `pypresence requests` in a virtual environment and run the standalone
script instead; see [optional package installation](getting-started.md#optional-python-packages).

Set `CYNTHIA_HOSTNAME` to the reachable hostname or IP and `CYNTHIA_PROTOCOL`
to `https://` or `http://`. The same values are used to build video links.
Start the client where Discord desktop is running:

```bash
python tools/cyclient.py
```

By default, the script uses the project's public application ID and art
assets. For a custom Discord application, upload Rich Presence art in the
Developer Portal and use these exact keys:

| Detected game | Asset key |
| --- | --- |
| Pokémon HOME | `pokemon_home_icon` |
| Pokémon: Let's Go, Pikachu! | `pokemon_lets_go_pikachu_icon` |
| Pokémon: Let's Go, Eevee! | `pokemon_lets_go_eevee_icon` |
| Pokémon Legends: Arceus | `pokemon_legends_arceus_icon` |
| Pokémon Legends: Z-A | `pokemon_legends_za_icon` |
| Pokémon Scarlet | `pokemon_scarlet_icon` |
| Pokémon Violet | `pokemon_violet_icon` |
| Pokémon Sword | `pokemon_sword_icon` |
| Pokémon Shield | `pokemon_shield_icon` |
| Pokémon Brilliant Diamond | `pokemon_brilliant_diamond_icon` |
| Pokémon Shining Pearl | `pokemon_shining_pearl_icon` |
| Pokémon FireRed Version | `pokemon_firered_icon` |
| Pokémon LeafGreen Version | `pokemon_leafgreen_icon` |
| Other recognized games or Switch home screen | `nintendo_switch` |

For scene tooling, `tools/scene_setup.html` can crop capture frames and
generate parameters for CV reference scenes.
