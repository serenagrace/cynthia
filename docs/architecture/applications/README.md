# Slash-command applications

**Source:** `cynthia/bot/applications/`; discovery and command syncing are
implemented in `cynthia/bot/applications/tree.py`.

## Discovery contract

`CommandTree` loads every direct Python module in `applications/`, excluding
`__init__.py` and `tree.py`, then reads its `__application__` export. The
export can be one command, an iterable of commands, or an application class;
classes receive the bot client and may implement `async __ainit__` and `apps()`.
Modules are reloaded before commands are synchronized.

Use the shared `interaction.client` services (configuration, permission
checks, Drive, database, daemon manager, and verification state) instead of
creating parallel service instances. Apply authorization with
`cynthia.utils.auth` decorators and/or `interaction.client.perms_check`.
Command modules should delegate long-running work to the owning cog, utility,
or daemon rather than duplicating its state.

## Module catalog

| Module | Command area |
| --- | --- |
| `apps.py` | Reload slash-command applications. |
| `auth.py` | Configure/inspect authorization and verification. |
| `cogs.py` | Reload cogs. |
| `config.py` | Read and update configuration. |
| `control.py` | Bot/process control and operational messages. |
| `daemons.py` | Reload eligible daemons. |
| `drive.py` | Upload/download files and context-menu uploads. |
| `guild.py` | Guild avatar and nickname administration. |
| `help.py` | Command help. |
| `llm.py` | Local chat/model controls. |
| `music.py` | Music playback and queue controls. |
| `nxbt.py` | Controller connect/disconnect and macro controls. |
| `shell.py` | Permission-gated configured shell commands. |
| `status.py` | Bot, daemon, and capture status. |
| `stream.py` | Web stream and OBS controls. |
| `test.py` | Explicit Discord screening/test commands. |
| `twitch.py` | Twitch and channel commands. |
| `web.py` | Optional game-data lookup commands. |

`tree.py` is discovery infrastructure, not an application module. Tests for
command behavior live in `tests/test_simulated_commands.py`; authorization
conventions and local checks are in the [development guide](../../development.md).
