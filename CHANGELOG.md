# Changelog

## 1.6.0

### Added
- Ternary macro steps: `scene ? true_macro : false_macro`.
- `/about` command with project version and startup details.
- Custom status, a scene setup tool (`tools/scene_setup.html`) and scene files.
- Quick settings guard during macros.
- Hunt watchdog, improved statistics and an improved video feed page.
- `tools/cyclient.py`, an optional Discord Rich Presence client with configurable host and protocol.
- Rich Presence game-title assets and OCR normalization for supported Pokémon games.
- Test suite (offline and opt-in live Discord checks) and GitHub Actions CI.
- isort and Black formatting.
- Sample macros in `examples/macros/` and boot-time deployment samples in `deploy/`.
- GPL-3.0-or-later `LICENSE` and Dependabot configuration.
- `.env.example`, `config.example.yaml` and `perms.example.yaml`.
- `STATUS_HOSTS` and `status_services` to configure the `/status` command.
- A full README covering install, Arch and Debian packages, Bluetooth and capture-card setup, macros and systemd.

### Changed
- Drive path, capture-card USB ID and command-sync guild are configured through `.env` (`DRIVE_PATH`, `ELGATO_USB_ID`, `SYNC_GUILD_ID`) instead of being hardcoded.
- `/pokemon` loads its dataset from the drive and disables itself when the file is missing.
- Docstrings added across the project; stray `print` calls moved to logging.
- `pyproject.toml` gained project metadata and no longer lists the package as its own dependency.
- `bin/run.sh` is documented and quotes its arguments.

### Fixed
- Race condition in the NXBT daemon.
- Race condition in the status cog when hunting state changes.
- Stale rotating status and Rich Presence after activity ends; status API failures without drive storage.
- Banning a user no longer requires a deleted state.
- The UVC reconnect path now awaits `setup()`.
- A missing-key error message in `Namespace` now includes the key.

### Removed
- The Roku command and its `roku` dependency.
- The `reload` option of `/cset`, which did nothing.

## 1.5.x

- **1.5.9**: reload commands for application modules and cogs; fixed OnMessage logging; changed some permission assignments; refactored applications.
- **1.5.8**: automatic logging to the correct hunt log; adjusted permission system and added permission control commands; fixed snowflake equality and hashing; fixed permission duplication.
- **1.5.7**: reboot and daemon reload commands; CYStream stats and faster backend; NXBT daemon recovers from controller disconnects.
- **1.5.6**: changed Bouncer filters; Insight no longer fails on kicks; viewer count endpoint in CYStream.
- **1.5.1–1.5.5**: Bouncer cog with Insight screening, greeting handling and status embed improvements.

Earlier history is in the Git log.
