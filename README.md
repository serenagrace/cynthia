# Cynthia

**Customizable Internal Network Task Handler + Interactive Assistant**

Cynthia is a Python Discord bot with slash commands, permission-aware controls, and optional integrations for Nintendo Switch, filesystem storage, and video capture.

## Video feed

[View Cynthia’s video feed](https://serenegrace.io/video_feed).

## Requirements

- Python 3.11
- A Discord bot token
- Linux. The Switch and capture-card features need Bluetooth, V4L2 and USB tools.
- Root access. NXBT drives Bluetooth directly, so `bin/run.sh` starts the bot with `sudo`.

Shiny hunting needs a Bluetooth adapter and a UVC capture card (tested with an Elgato 4K X) exposed as `/dev/video*`.

### System packages

Debian or Ubuntu:

```bash
sudo apt install bluez v4l-utils usbutils tmux
```

Arch Linux:

```bash
sudo pacman -S bluez bluez-utils bluez-deprecated-tools v4l-utils usbutils tmux
sudo systemctl enable --now bluetooth.service
```

- `bluez-utils` provides `bluetoothctl`.
- `bluez-deprecated-tools` provides `hciconfig`, `hcitool` and `sdptool`, which NXBT requires. On Arch they are not in `bluez-utils`.
- `v4l-utils` provides `v4l2-ctl`; `usbutils` provides `lsusb` and `usbreset`.
- `tmux` is only needed for the boot-time service in `deploy/`.

Arch has no `python311` in its official repositories. Install the AUR package `python311` with your AUR helper, review its build files first, and use `python3.11` for the virtual environment below.

### Bluetooth notes

- Check the adapter with `bluetoothctl list` and `hciconfig`.
- NXBT writes a runtime drop-in at `/run/systemd/system/bluetooth.service.d/nxbt.conf` that starts `bluetoothd` with `--compat --noplugin=*`, then restarts bluetooth. Other Bluetooth devices (headsets, mice) may disconnect while the bot runs. No permanent change is made to `/etc/bluetooth`; the stock files work.
- Pairing a Switch is finicky. If it fails, restart `bluetooth.service`, make sure nothing else is using the adapter, and retry.

### Capture card notes

- Check the card with `lsusb | grep -i elgato` and `v4l2-ctl --list-devices`.
- Add the service user to the `video`, `plugdev` and `bluetooth` groups (`sudo usermod -aG video,plugdev,bluetooth youruser`), then log in again.
- `deploy/99-elgato-capture.rules` is a udev rule that lets the `plugdev` group open Elgato 4K X and 4K S cards. Install it with:

```bash
sudo cp deploy/99-elgato-capture.rules /etc/udev/rules.d/
sudo udevadm control --reload && sudo udevadm trigger
```

- At startup the UVC daemon runs `usbreset` on the card named by `ELGATO_USB_ID`, which clears a wedged device. Leave the variable empty to skip the reset. The ID is the `vendor:product` pair from `lsusb` (for example `0fd9:009b`), not a GUID.

## Install

```bash
python3.11 -m venv env
source env/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Use `env` as the virtualenv name: `bin/run.sh` and the `deploy/` scripts expect `env/bin/cynthia`.

The `nxbt` dependency installs directly from [serenagrace/nxbt](https://github.com/serenagrace/nxbt), branch `cynthia-patches`, as configured in `pyproject.toml`.

Copy the example files and edit them. They are private runtime files and Git ignores the real ones:

```bash
cp .env.example .env
cp config.example.yaml config.yaml
cp perms.example.yaml perms.yaml
```

### `.env`

| Variable | Required | Purpose |
| --- | --- | --- |
| `DISCORD_BOT_TOKEN` | yes | Discord bot token. |
| `OTP_SECRET` | no | TOTP secret for owner verification. Verification is disabled when unset. |
| `DRIVE_PATH` | no | Directory for macros, database, logs and datasets. Overrides `drive_path` in `config.yaml`. |
| `ELGATO_USB_ID` | no | Capture card `vendor:product` from `lsusb`. Reset with `usbreset` at startup; skipped when empty. |
| `SYNC_GUILD_ID` | no | Guild that receives slash commands immediately after each sync. Global sync still happens. |
| `STATUS_HOSTS` | no | Comma-separated hostnames or IPs the owner's `/status` command pings. Defaults to `discord.com,github.com,google.com`. |

Values in the process environment win over `.env`.

### `config.yaml`

| Key | Purpose |
| --- | --- |
| `owner` | Discord user ID of the bot owner. |
| `drive_path` | Drive directory, used when `DRIVE_PATH` is unset. Use `null` to disable drive-backed features. |
| `silent` | Send bot messages as silent Discord messages (no notification) unless they are alerts. |
| `status_services` | systemd units `/status` checks. Defaults to `cynthia.service`. |

### `perms.yaml`

Permission lists default to empty and the configured owner is added automatically, except to `allowed_commands`. Entries look like `+u:<id>` (allow) or `-u:<id>` (deny), where `u` is a user, `r` a role and `g` a guild. A `global` block applies everywhere; a `g:<guild id>` block adds to it for one guild. See `perms.example.yaml`.

### The drive

The drive directory holds runtime state:

- `macros.json`: saved Switch macros
- `cynthia.db`: Discord logging and OnMessage rules
- `pokemonDB_dataset.csv`: species data for `/pokemon`. Provide it yourself; `/pokemon` is disabled when it is missing.
- `encounter_times.log`, `user_status.json`, `activity_stats.json`, `uvicorn_access.log.gz` and a gzipped message log

## Run

```bash
bin/run.sh --config config.yaml --perms perms.yaml
```

`bin/run.sh` runs `sudo env/bin/cynthia` in a loop: exit codes 0 and 1 stop it, anything else restarts the bot. The user needs passwordless `sudo`. Both options default to the filenames above. The bot loads slash commands and cogs at startup and writes updated configuration and permissions back to their files when it exits.

The bot also serves a local FastAPI app on `127.0.0.1:8000` (the video feed page and `/api/*` endpoints). Put a reverse proxy such as nginx in front of it to publish it.

## Start at boot

`deploy/` has sample files for running the bot in a detached tmux session from systemd:

| File | Install to | Purpose |
| --- | --- | --- |
| `cynthia.service` | `/etc/systemd/system/` | systemd unit. Set `User=` to the account that owns the checkout. |
| `cynthia.sh` | `/usr/local/bin/` | Creates a `cynthia` tmux session: window 0 runs `bin/run.sh`, window 1 is a spare shell. Set `CYNTHIA_DIR` at the top. |
| `99-elgato-capture.rules` | `/etc/udev/rules.d/` | Capture card permissions (see above). |

```bash
sudo cp deploy/cynthia.service /etc/systemd/system/
sudo install -m 755 deploy/cynthia.sh /usr/local/bin/cynthia.sh
sudo systemctl daemon-reload
sudo systemctl enable --now cynthia.service
tmux attach -t cynthia
```

Edit the copies in place before enabling the service; the paths and user in the samples are placeholders.

## Troubleshooting

| Check | Command |
| --- | --- |
| Bluetooth adapter | `bluetoothctl list`, `hciconfig` |
| Capture card | `lsusb`, `v4l2-ctl --list-devices` |
| Group membership | `id` |
| Service logs | `systemctl status cynthia.service`, `tmux attach -t cynthia` |

## Nintendo Switch macros

Macros are line-based sequences of controller inputs. On Discord, send a message containing the macro, then use its **Define Macro** context-menu action to save it. Start the message with `$name` on its own line; the remaining lines are the macro body. Names are case-insensitive, and spaces in names become underscores.

```text
$soft_reset
hold =
wait
tap A
```

Each body line describes one step. Buttons on the same line are pressed together; separate lines run in order. Supported button tokens are `a`, `b`, `x`, `y`, `l`, `r`, `zl`, `zr`, `ls`, `rs`, `6` (up), `v` (down), `,` (left), `.` (right), `=` (plus), `-` (minus), `h` (home), `c` (capture), `lsl`, `lsr`, `rsl`, and `rsr`. Button names are case-insensitive.

Use `tap`, `hold`, or `wait` before a step to set its timing: tap presses for 0.05 seconds, hold for 1 second, and wait sleeps for 1 second. Default presses use 0.15 seconds down and 0.15 seconds up. Custom timing uses `(down,up)` in seconds, such as `(0.3,0.2) A`. Add `noblock` to a step to make NXBT return without waiting for that press to finish.

Call another saved macro by name in a body line. For example, a line containing `soft_reset` runs that macro. Use `/get_macro` to inspect a definition and `/queue_macro` to queue one for playback. The built-in `zoom` and `cleanup` macros are available. Start a definition with `$!name` to replace an existing macro with that name.

Macro definitions persist in `macros.json` under the configured `drive_path`; without an enabled drive, definitions are not saved across restarts. Conditional steps use `scene ? true_macro : false_macro`; they wait up to one second for a matching video scene, then run the selected macro. For example, `home ? cleanup : zoom` selects based on whether the Switch home screen was detected.

### Shifted tokens and name collisions

Saved macros store directions in shifted form: `^` (up), `V` (down), `<` (left), `>` (right), `H` (home) and `+` (plus). Both forms parse, so `6`, `v`, `,`, `.`, `h` and `=` are equivalent.

Macro names are matched as substrings of a line. A very short name such as `a` or `d` can collide with button tokens, so use descriptive names.

### Sample macros

`examples/macros/` has shiny-hunting macros for BDSP: `mespirit` (Mesprit), `cresselia`, `shaymin`, `arceus` and `darkrai`, plus the helpers they call (`roamer_decide`, `encounter_roamer`, `roamer_reroll`, `screen_record`, `pause` and `run_up_down`). Each file starts with its `$name` line. Paste each file's contents into Discord and use **Define Macro**. Define the helper macros before the target macro; saved definitions persist in the configured drive.

These macros need a working Switch capture feed and the CV daemon. In BDSP settings, set **Text Box** to style 22 for reliable scene matching. Save in front of the target with the game open, then leave the Switch at the **Change Grip/Order** menu.

Connect and start a hunt with the target name and matching macro name:

```text
/connect
/set_hunt Darkrai
/queue_macro darkrai
/unpause
```

Replace `Darkrai` and `darkrai` with your target and its macro name. The Mesprit macro is named `mespirit`. `cyclient` is optional; run it on your desktop to sync your Discord Rich Presence with the bot's detected game status.

The conditional steps use scenes such as `route_202`, `roamer` and `bdsp_run`, provided by the CV daemon.

## Tools

- `tools/scene_setup.html`: open it in a browser to crop a capture frame and generate scene parameters for the CV daemon.
- `tools/cyclient.py`: optional Discord Rich Presence client. Install its dependencies with `python -m pip install -e ".[cyclient]"`.

`cyclient` uses Discord Rich Presence art keys `pokemon_home`, `pokemon_legends_arceus`, `pokemon_legends_za`, `pokemon_scarlet_violet` and `pokemon_sword_shield` for supported Pokémon titles. Upload artwork you have permission to use under those exact names in your Discord application's **Rich Presence > Art Assets**. Game artwork is not included in this repository.

## Development

Run the local test suite without opt-in live Discord checks:

```bash
python -m pytest -m "not discord_live"
```

Format Python files with:

```bash
bin/black.sh
```

Slash-command modules live in `cynthia/bot/applications/`; cogs live in `cynthia/bot/cogs/`; daemon integrations live in `cynthia/daemons/`. The bot discovers command modules and daemons automatically at startup.

## License

Cynthia is licensed under the [GNU General Public License v3.0 or later](LICENSE). See [CHANGELOG.md](CHANGELOG.md) for release notes.
