# Cynthia contributor instructions

## Setup and validation

- The package requires **Python 3.11** (`requires-python=">=3.11,<3.12"` in `pyproject.toml`); `paddlepaddle==3.2.2` and `numpy<2` have no Python 3.14 wheels. `tools/cyclient.py` is a standalone script (`cyclient` extra) and is not tied to this constraint. Install it with `python -m pip install -e ".[cpu]"` (or `".[gpu]"` with Paddle's CUDA index, see README); the `cynthia` console entry point resolves to `cynthia.__main__:main`.
- Run the bot with `cynthia --config config.yaml --perms perms.yaml`. It reads `DISCORD_BOT_TOKEN` (required) and `OTP_SECRET` (optional) from the repository-root `.env`. `config.yaml` must exist; its values are merged over `context.defaults.Defaults`.
- Format Python with `bin/black.sh`; it runs Black over the repository using the `py311` target. There is a pytest suite in `tests/` (`python -m pytest`; `-m "not discord_live"` skips the live-bot checks). `cynthia/bot/applications/test.py` defines Discord test commands, not Python tests.
- Copilot CLI's `.github/mcp.json` exposes only the read-only `/api/user_status` and `/api/viewers` endpoints. Start the bot so the local FastAPI daemon serves its OpenAPI spec at `http://127.0.0.1:8000/openapi.json` before using those tools.

## Architecture

- `cynthia.__main__` builds a `Context`, starts `Bot`, then persists the in-memory config and permissions mappings when the process exits. `Context` owns the config, permission, environment, and app-metadata loaders.
- `Bot` is the Discord integration root. It creates the optional filesystem `Drive`, SQLite `Database`, logging, message responder, and `DMan` daemon manager. A missing or invalid `drive_path` disables drive/database-backed features rather than preventing startup.
- Slash-command modules live in `cynthia/bot/applications/`. `CommandTree` discovers every direct `.py` file in that directory (except `__init__.py` and `tree.py`) and reloads them before syncing commands. The bot recursively discovers cog modules under `cynthia/bot/cogs/`.
- `DMan` discovers `Daemon` subclasses in direct modules under `cynthia/daemons/`, creates shared-memory frame buffers, and starts every discovered daemon during bot construction. Daemons must honor their manager namespace's `run` flag so `Bot.close()` can shut them down.
- The drive-backed SQLite database (`cynthia.db`) stores Discord logging and `OnMessage` rules. Those rules are loaded after Discord is ready and saved during cleanup.

## Extension conventions

- Never store secrets or tokens on the drive. Keep secret files in the bot's working directory and gitignore them.
- A command module must assign `__application__` to a command, an iterable of commands, or an application class. Application classes receive the bot client, may implement `async __ainit__`, and provide `apps()`.
- A cog module must expose `async def setup(bot)` and register its cog there; it will be found automatically, including in nested cog directories.
- Use `interaction.client` to access shared services (`config`, `perms_check`, `drive`, `database`, `dman`, and `verify`) inside commands and views.
- Enforce authorization with the existing decorators in `cynthia.utils.auth` and/or `interaction.client.perms_check`. Permission files are merged per `global` and guild contexts; the configured owner is added to each non-command permission list.
- Keep config changes compatible with `Namespace`: configuration is accessed and mutated through its mapping-style helpers, then written back by `Context.update_config()` at shutdown.
