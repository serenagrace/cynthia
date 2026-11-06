# Cynthia

[![Tests](https://github.com/serenagrace/cynthia/actions/workflows/tests.yml/badge.svg)](https://github.com/serenagrace/cynthia/actions/workflows/tests.yml)
[![License: GPL v3](https://img.shields.io/badge/license-GPL--3.0--or--later-blue.svg)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![discord.py](https://img.shields.io/badge/discord.py-bot-5865F2?logo=discord&logoColor=white)](https://github.com/Rapptz/discord.py)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Platform: Linux](https://img.shields.io/badge/platform-linux-FCC624?logo=linux&logoColor=black)](#requirements)
[![Version](https://img.shields.io/badge/version-1.8.0-success.svg)](CHANGELOG.md)

**Customizable Internal Network Task Handler + Interactive Assistant**

Cynthia is a Python Discord bot with slash commands, permission-aware controls, and optional integrations for Nintendo Switch, filesystem storage, and video capture.

### Features

- **Nintendo Switch control and automation:** connect over Bluetooth, send controller inputs from Discord, and define, save, queue, pause, or loop macros. Macros support simultaneous buttons, custom timing, nested macros, and conditional branches based on detected scenes. Sample BDSP hunting macros include their helper dependencies.
- **Computer vision and shiny hunting:** compare capture frames with reference scenes, read selected game titles with OCR, and track encounter timing for supported BDSP hunts. Possible shinies pause automation and alert the owner with a capture image. Encounter logs support hunt statistics, while watchdogs and encounter-reset logic help stalled macros recover. Other recognized game titles provide status information, not universal encounter detection.
- **Live video and streaming:** watch the capture feed in a browser through WebRTC, with an MJPEG fallback, or send hardware-encoded video and capture-card audio to OBS. Discord commands control video modes, recordings, scene previews, and layouts. Overlay panes show inputs, scene scores, hunt statistics, Twitch chat, and the bot version. Feed watchdogs recycle persistently slow encoders, and measured OBS video age keeps input and scene overlays synchronized.
- **Twitch integration:** start and stop broadcasts with button confirmation, check stream health, and share the channel link with live status. Optional authorization enables automatic hunt titles, game categories, and delayed clips for possible shinies. Configurable safeguards restart long broadcasts and stop streams after prolonged capture-card signal loss.
- **Music in Discord voice channels:** play YouTube searches, direct links, playlists, and albums; manage playback and per-server queues; and pin preferred results. Search ranking favors relevant tracks over covers, remixes, and unrelated recordings unless requested.
- **Server tools and permissions:** manage command allowlists and permissions by user, role, or guild; configure message-log channels; and change the bot's server nickname or avatar. Optional member screening provides interactive insights, greetings, and moderation actions, including automated kick/ban rules when the bot has the configured Bouncer role.
- **Host administration and storage:** check configured services and network hosts, manage configuration, upload or download drive files, and run authorized shell commands. Reload commands, cogs, or daemons and control bot restarts, shutdowns, and host reboots from Discord. An enabled drive persists macros, logs, message-trigger rules, and integration state.
- **Status and external integrations:** publish game, hunt, and custom activity status through the local web API; expose plain-text StreamElements commands; and mirror activity into desktop Discord Rich Presence with the optional `cyclient` script. A Pokémon lookup command is available when its species dataset is supplied.
- **Twitch chat persona:** a local, GPU-hosted Ollama model reads Twitch chat and answers in chat or aloud on stream. It remembers chatters, remarks on hunt events, and is moderated, rate-capped and fully switchable from owner-only `/llm` commands.

Integrations depend on the relevant hardware, credentials, datasets, and permissions.
Command modules, cogs, and daemons are discovered automatically, so the bot can
be extended without maintaining a central registration list. Installation and
configuration come first below; detailed streaming and macro instructions follow.

## Requirements

- Python 3.11
- A Discord bot token
- Linux. The Switch and capture-card features need Bluetooth, V4L2 and USB tools.
- Root access. NXBT drives Bluetooth directly, so `bin/run.sh` starts the bot with `sudo`.

Shiny hunting needs a Bluetooth adapter and a UVC capture card (tested with an Elgato 4K X) exposed as `/dev/video*`.

### System packages

Debian or Ubuntu:

```bash
sudo apt install bluez v4l-utils usbutils tmux ffmpeg libopus0
# Optional, for the headless OBS setup:
sudo apt install obs-studio xvfb
```

Arch Linux:

```bash
sudo pacman -S bluez bluez-utils bluez-deprecated-tools v4l-utils usbutils tmux ffmpeg opus
# Optional, for the headless OBS setup (the browser plugin draws the overlay panes):
sudo pacman -S obs-studio obs-studio-plugin-browser xorg-server-xvfb
sudo systemctl enable --now bluetooth.service
```

- `bluez-utils` provides `bluetoothctl`.
- `bluez-deprecated-tools` provides `hciconfig`, `hcitool` and `sdptool`, which NXBT requires. On Arch they are not in `bluez-utils`.
- `v4l-utils` provides `v4l2-ctl`; `usbutils` provides `lsusb` and `usbreset`.
- `tmux` is only needed for the boot-time service in `deploy/`.
- `ffmpeg` and `opus` are needed for `/music` voice playback.

Arch has no `python311` in its official repositories. Install the AUR package `python311` with your AUR helper, review its build files first, and use `python3.11` for the virtual environment below.

### Bluetooth notes

- Check the adapter with `bluetoothctl list` and `hciconfig`.
- NXBT writes a runtime drop-in at `/run/systemd/system/bluetooth.service.d/nxbt.conf` that starts `bluetoothd` with `--compat --noplugin=*`, then restarts bluetooth. Other Bluetooth devices (headsets, mice) may disconnect while the bot runs. No permanent change is made to `/etc/bluetooth`; the stock files work.
- Pairing a Switch is finicky. To do so, open the Change Grip/Order Menu and run `/connect`. If this fails, first try again, then try restarting the bot. At worst, restart `bluetooth.service`, make sure nothing else is using the adapter, and retry. Refer to the [nxbt github](https://github.com/serenagrace/cynthia) for more information on pairing, etc.

### Capture card notes

- Check the card with `lsusb | grep -i elgato` and `v4l2-ctl --list-devices`.
- Add the service user to the `video`, `plugdev` and `bluetooth` groups (`sudo usermod -aG video,plugdev,bluetooth youruser`), then log in again.
- `deploy/99-elgato-capture.rules` is a udev rule that lets the `plugdev` group open Elgato 4K X and 4K S cards. Install it with:

```bash
sudo cp deploy/99-elgato-capture.rules /etc/udev/rules.d/
sudo udevadm control --reload && sudo udevadm trigger
```

- At startup the UVC daemon runs `usbreset` on the card named by `ELGATO_USB_ID`, which clears a wedged device. Leave the variable empty to skip the reset. The ID is the `vendor:product` pair from `lsusb` (for example `0fd9:009b`), not a GUID.

### Dependency updates

The OCR stack is upgraded manually as a compatible set. PaddleOCR 3.7.0 requires
PaddleX 3.7.x, whose releases require exactly `PyYAML==6.0.2`; independently
bumping PyYAML to 6.0.3 fails dependency resolution. OpenCV 4.9 wheels cannot
import with NumPy 2, while OpenCV 4.12 and 5.0 require NumPy 2 on Python 3.11.
The current `opencv-python-headless<5.1` range resolves to 4.11 with
`numpy<2.0.0`. Keep the NumPy cap until the numerical-stack migration is
reviewed together.

`.github/dependabot.yml` ignores routine major, minor and patch updates for
PyYAML, NumPy, OpenCV headless, PaddleOCR and both CPU/GPU PaddlePaddle packages.
The Paddle packages are held for coordinated review, not because every newer
release is known to fail. Before changing the pins or removing an ignore entry,
check dependency resolution, the test suite and real OCR on the supported CPU
and GPU installations. Security updates are not excluded by these semver rules,
and Dependabot alerts, other Python packages (including setuptools) and GitHub
Actions updates remain unaffected.

## Install

```bash
python3.11 -m venv env
source env/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,cpu]"
```

Choose one PaddlePaddle build with an extra. Use `cpu` (above) on any machine. On an NVIDIA GPU, use `gpu` instead, which makes OCR roughly 7x faster; it needs a CUDA 12.6-compatible driver and Paddle's package index:

```bash
python -m pip install -e ".[dev,gpu]" --extra-index-url https://www.paddlepaddle.org.cn/packages/stable/cu126/
```

Do not install both extras. To switch an existing environment, uninstall the other build first (`pip uninstall paddlepaddle` or `paddlepaddle-gpu`). The bot uses the GPU when Paddle was built with CUDA and falls back to the CPU otherwise.

Use `env` as the virtualenv name: `bin/run.sh` and the `deploy/` scripts expect `env/bin/cynthia`.

After changing the package version, refresh the installed metadata without
changing dependencies, then restart the bot with `/restart`:

```bash
bin/install.sh
```

The script verifies that the installed version matches `pyproject.toml`. The
restart is required before `/about` and the OBS watermark show the new version.
Both add `-alpha` (for example `1.8.0-alpha`) when the running checkout has
uncommitted changes to `cynthia/` or `pyproject.toml`, or its commit isn't on
`origin/master`. This is checked once at startup against the local
`origin/master` ref, so run `git fetch` after a release is merged elsewhere.

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
| `OBS_WS_HOST` / `OBS_WS_PORT` / `OBS_WS_PASSWORD` | no | obs-websocket address (default `127.0.0.1:4455`) and password. |
| `TWITCH_STREAM_KEY` / `OBS_STREAM_KEY` | no | Stream key for `/twitch`. The Twitch one wins. |
| `TWITCH_CHANNEL` | no | Channel for the chat overlay, `/twitchurl` and the chat model. |
| `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` | no | Twitch application that sets the stream title and category after `/twitch auth`. The secret is only for confidential clients. |
| `STATUS_HOSTS` | no | Comma-separated hostnames or IPs the owner's `/status` command pings. Defaults to `discord.com,github.com,google.com`. |

Values in the process environment win over `.env`.

### `config.yaml`

| Key | Purpose |
| --- | --- |
| `owner` | Discord user ID of the bot owner. |
| `drive_path` | Drive directory, used when `DRIVE_PATH` is unset. Use `null` to disable drive-backed features. |
| `silent` | Send bot messages as silent Discord messages (no notification) unless they are alerts. |
| `encounter_reset` | Restart the looping macro from the start 5 seconds after each detected encounter, unless the shiny stop fired. Defaults to `true`; set `false` to disable. |
| `status_services` | systemd units `/status` checks. Defaults to `cynthia.service`. |
| `obs_feed` | Send the video to OBS while OBS is running. Defaults to `true`. |
| `obs_feed_port` | UDP port on `127.0.0.1` for the OBS feed. Defaults to `5000`. |
| `obs_fps` / `obs_height` | OBS frame rate (15, 24, 30, 60) and resolution (480, 720, 1080). Defaults to `60` and `1080`. |
| `web_fps` / `web_height` | The same for the web viewer. Defaults to `30` and `720`. |
| `obs_scene` | OBS scene the bot manages. Defaults to `Cynthia`. |
| `obs_layout_file` | OBS pane layout. Defaults to `obs_layout.yaml`. |
| `twitch_bitrate_kbps` | Video bitrate for Twitch streams (OBS Simple output mode). Defaults to `6000`. |
| `twitch_no_signal_stop_minutes` | Stop the stream once the capture card's no-signal screen has been up this long. Defaults to `10`; `0` disables it. |
| `capture_freeze_seconds` | Reset the capture card (restart the capture daemon, with `usbreset` when `ELGATO_USB_ID` is set) when frames keep arriving but the picture has not changed for this many seconds, and DM the owner. The no-signal screen is ignored. Repeated failures wait twice as long each time, up to 16 times this value. Defaults to `120`; `0` disables it. |
| `twitch_auto_clip` | Clip the stream when a shiny is found. Defaults to `true`; needs `/twitch auth`. |
| `twitch_clip_delay_seconds` | Seconds to wait after the shiny shows on the input visualizer (`obs_feed_delay_ms` + `obs_overlay_lag_ms`) before clipping, so the moment has reached Twitch (Twitch clips the 30 seconds before the request). Defaults to `10`. |
| `twitch_restart_hours` | Stop and restart a stream once it has run this long, since Twitch ends broadcasts at 48 hours. The owner gets a DM. Defaults to `24`; `0` disables it. |
| `twitch_reboot_message` | Fixed Twitch chat message (not the chat model) posted on `/restart` and `/reboot` while OBS is streaming. Defaults to `be right back, rebooting real quick!`; `""` disables it. |
| `twitch_goodbye_message` | Fixed Twitch chat message posted on `/shutdown`, which then ends the stream after 5 seconds so the message shows on it. Defaults to `that's all for now, thanks for hanging out! bye!`; `""` skips the message (the stream still ends). |
| `twitch_auto_info` | Set the Twitch title and category from the detected game and hunt. Defaults to `true`; it does nothing until `/twitch auth` has been run. |
| `twitch_info_confirm_seconds` | How long a new game or hunt must hold before the channel is changed. Defaults to `60`. |
| `twitch_categories` | Map a detected game title to a Twitch category name or id when Twitch names it differently. Defaults to `{}`. |
| `obs_feed_bitrate` | H.264 (NVENC) bitrate of the OBS feed. Defaults to `50M`. |
| `obs_feed_delay_ms` | Hold the OBS feed back this long (a safety buffer that smooths bursts and audio stalls). Defaults to `1000`; `0` disables it. |
| `obs_overlay_lag_ms` | Extra delay, on top of `obs_feed_delay_ms`, for the OBS overlay's inputs and scene-match panes so they line up with the video OBS shows (which also trails by encode, OBS buffering and decode time). Defaults to `1700`. |

### `perms.yaml`

Permission lists default to empty and the configured owner is added automatically, except to `allowed_commands`. Entries look like `+u:<id>` (allow) or `-u:<id>` (deny), where `u` is a user, `r` a role and `g` a guild. A `global` block applies everywhere; a `g:<guild id>` block adds to it for one guild. See `perms.example.yaml`.

### The drive

The drive directory holds runtime state:

- `macros.json`: saved Switch macros
- `cynthia.db`: Discord logging and OnMessage rules
- `cynthia.log` (and `cynthia.log.1` … `.10`): the full bot log from every process, including macro steps; rotated at 20 MB
- `pokemonDB_dataset.csv`: species data for `/pokemon`. Provide it yourself; `/pokemon` is disabled when it is missing.
- `encounter_times.log`, `user_status.json`, `activity_stats.json`, `uvicorn_access.log.gz` and a gzipped message log
- `twitch_channel.json`: the last game and hunt sent to Twitch

Secrets never belong on the drive. `.env`, `twitch_token.json` and `twitch_chat_token.json` stay in the bot's working directory and are ignored by Git. The token files are readable only by the bot's user.

## Run

```bash
bin/run.sh --config config.yaml --perms perms.yaml
```

`bin/run.sh` runs `sudo env/bin/cynthia` in a loop: exit codes 0 and 1 stop it, anything else restarts the bot. The user needs passwordless `sudo`. Both options default to the filenames above. Add `-v` (`--verbose`) to also show every macro step on the console; `cynthia.log` on the drive always has them. The bot loads slash commands and cogs at startup and writes updated configuration and permissions back to their files when it exits.

The bot also serves a local FastAPI app on `127.0.0.1:8000` (the video feed page and `/api/*` endpoints). Put a reverse proxy such as nginx in front of it to publish it.

These endpoints return plain text for StreamElements custom commands (allow them in the reverse proxy too):

- `/api/streamelements/uptime`: how long the bot has been running, e.g. `has been running for 3 hours and 5 minutes`.
- `/api/streamelements/online`: always `True`; a request that fails means the bot is down.
- `/api/streamelements/description`: the hunt (`hunting shiny Cresselia`, or `trying to get a shiny Mew` for a self encounter), else the `/set_status` text, else `not doing anything in particular right now`.

Use them in a command such as `Cynthia ${customapi.https://example.com/api/streamelements/description}`.

## Start at boot

`deploy/` has sample files for running the bot in a detached tmux session from systemd:

| File | Install to | Purpose |
| --- | --- | --- |
| `cynthia.service` | `/etc/systemd/system/` | systemd unit. Set `User=` to the account that owns the checkout. |
| `cynthia.sh` | `/usr/local/bin/` | Creates a `cynthia` tmux session: window 0 runs `bin/run.sh`, window 1 is a spare shell, window 2 runs headless OBS (`bin/obs.sh`). Set `CYNTHIA_DIR` at the top. |
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

## Video feed

[View Cynthia’s video feed](https://serenegrace.io/video_feed).

### Sending the feed to OBS

While OBS Studio is open, the bot encodes the capture with NVENC (H.264, BT.709, MPEG-TS) and sends it to `udp://127.0.0.1:5000`; it stops when OBS closes. This needs an NVIDIA GPU and an `ffmpeg` with `h264_nvenc`. In OBS, use *Scene Collection → Import* and pick `deploy/obs/Cynthia.json` (the feed and default overlay panes at 1080p60), or add a Media Source with the URL `udp://127.0.0.1:5000?overrun_nonfatal=1&fifo_size=5000000&buffer_size=4194304` and the input format `mpegts`. The `buffer_size` matters: with the default socket buffer a busy receiver drops UDP packets, which shows up as stutters and audio gaps. The feed carries AAC audio from the capture card. Set `obs_feed: always` to send it even when OBS is closed. From there OBS can stream to Twitch or YouTube.

#### Controlling OBS from Discord

The bot drives OBS through obs-websocket (Tools → WebSocket Server Settings, or `"server_enabled": true` in `~/.config/obs-studio/plugin_config/obs-websocket/config.json`); put the password in `OBS_WS_PASSWORD`. The web viewer uses WebRTC when the `mediamtx` binary is on `PATH` (download from github.com/bluenviron/mediamtx) and falls back to MJPEG otherwise; see the `webrtc*` config keys. The OBS browser plugin (`obs-studio-plugin-browser` on Arch) is needed for the overlay panes. `bin/obs.sh` runs OBS headless and restarts it. It starts a virtual-monitor NVIDIA Xorg server (`deploy/xorg-headless.conf`, display `:98`, needs `sudo -n` unless run as root) so OBS composites on the GPU, and falls back to `xvfb-run` with software OpenGL, which can use several CPU cores; `deploy/cynthia.sh` starts it in window 2 of the tmux session.

All of these are owner-only and DM-only:

- `/twitch start | stop | test | uptime | status`: stream to Twitch with `TWITCH_STREAM_KEY` (or `OBS_STREAM_KEY`). `test` uses Twitch's bandwidth-test mode, so nothing goes live. `start` and `stop` ask you to confirm with a button first, so they can't go off by accident. Only the person who ran the command can press it, and after a minute the buttons expire and nothing changes.
- `/twitch auth`: let the bot set the channel's title and category and clip shinies (see below).
- `/twitch clearchat`: choose a message from a dropdown to remove from the chat pane, or press **Clear pane** to remove them all. Add `user` to remove that Twitch user's existing messages instead. These owner-only controls affect the pane only, not Twitch chat or LLM memory; new messages still appear.
- `/obs framerate | resolution | record | stop | layout | show`, `/webstream framerate | resolution`: web and OBS frame rate and resolution are set independently and apply live. CV is always limited to 30 fps. The capture card runs at the cheapest mode that covers every running endpoint (OBS counts only while streaming or recording, the web stream only while someone watches), never below 720p for CV.

`/twitchurl` is open to everyone, anywhere: it posts the `TWITCH_CHANNEL` link and says whether the channel is live. Once `/twitch auth` has been run it asks Twitch, so a bandwidth test counts as offline; otherwise it goes by whether OBS is streaming.

The OBS scene is built from `obs_layout.yaml` (copy `obs_layout.example.yaml`): panes for the video, input visualizer, SSIM scores, hunt statistics (titled by the current activity), Twitch chat (`TWITCH_CHANNEL`) and a small `Cynthia (version)` watermark in the bottom-right corner. The reverse proxy in front of the web viewer must allow `/api/sync`, `/api/stream_stats` and `/api/activity_stats`.

#### Feed recovery and overlay synchronization

Both OBS and WebRTC feeds monitor fresh-frame throughput. After a 15-second startup grace period, two consecutive 15-second windows below half the available frame rate recycle only the affected FFmpeg encoder through its normal retry path. Static images, lower requested output rates, and stopped capture do not trigger recovery. This briefly interrupts that feed without restarting the bot or its macros.

The `OverlaySyncCog` checks OBS's displayed video against a small history of capture thumbnails every five seconds while streaming or recording. Three consistent, unambiguous matches among the last five (within a minute) gradually adjust the input visualizer and scene-score delay, by at most 250 ms per check. Ambiguous checks don't discard earlier matches, and one outlier is outvoted. It ignores timing differences below 100 ms and does not restart video or change WebRTC timing. Static or repeating scenes retain the last confirmed delay; disconnects and source restarts restore the configured fallback. Matching supports up to ten seconds of video age; a larger backlog cannot be corrected automatically.

| Setting | Default | Purpose |
| --- | --- | --- |
| `obs_auto_sync` | `true` | Measure OBS video age and adjust overlay timing automatically. Set `false` for fixed timing. |
| `obs_feed_delay_ms` | `1000` | Fixed holdback of the OBS video/audio feed. |
| `obs_overlay_lag_ms` | `1700` | Additional overlay delay used with the feed delay as the fallback. |

`/api/stream_stats` reports the effective `obs_overlay_delay_ms`. If the synchronization cog stops publishing for 30 seconds, overlays return to the configured fallback. Automatic synchronization adjusts overlay timing, not OBS's internal video buffer; adding a fixed OBS delay alone does not prevent buffer drift. A custom `?lag=<ms>` on the input pane URL adds a separate delay, so remove manual tuning when relying on measured synchronization.

Restart Cynthia after upgrading to activate the new feed watchdogs and synchronization cog; reinstallation does not reload running daemon processes.

#### Twitch title, category and clips

The bot can set the channel's category to the detected game and its title to the hunt (for example "Hunting shiny Cresselia"):

1. Register an application at [dev.twitch.tv/console](https://dev.twitch.tv/console) and put its `TWITCH_CLIENT_ID` (and `TWITCH_CLIENT_SECRET` for a confidential client) in `.env`. Restart the bot.
2. Run `/twitch auth`, open the link it sends and approve the code. The token is kept in `twitch_token.json` in the bot's working directory and renewed automatically. Once you confirm, `/twitch start` asks for this itself when the token is missing, lacks a scope or has been revoked, and starts the stream once you approve (or after 5 minutes); otherwise it starts straight away. With a confidential client (`TWITCH_CLIENT_SECRET` set) the token doesn't lapse, so one approval lasts until you revoke it; a public client's token lapses after 30 days unused.

When upgrading from a version that stored Twitch tokens on the drive, stop the bot first. Move `twitch_token.json` and `twitch_chat_token.json`, if present, from the drive into the bot's working directory. Do not overwrite existing token files; resolve any conflicts before restarting. Keep the files owned by the bot user with permissions `600`. The old version reads tokens from the drive, so moving them back is required before rolling back.

The channel changes only when the bot is sure and only when something new is detected. A game counts once it has been playing (not on the HOME screen) for `twitch_info_confirm_seconds` and it is one of the known titles. The category and title are then set once. They are not touched again, even if you edit them on Twitch, until a different game is detected or a different hunt is set. Clearing the hunt or returning to HOME never changes them. Without a hunt only the category is set. The last applied game and hunt are kept in `twitch_channel.json`, so a restart doesn't reapply them. If no Twitch category has exactly the game's name, the category is left alone; map it in `twitch_categories`.

When the hunt stops for a possible shiny while the stream is live, the bot waits as long as the effective OBS overlay delay plus `twitch_clip_delay_seconds`, so the moment has reached Twitch, then creates a 30-second clip titled after the hunt, and DMs you its edit link. The overlay delay uses the measured value when available, otherwise `obs_feed_delay_ms + obs_overlay_lag_ms`; it excludes any custom browser-source `?lag=<ms>`. Clipping needs the `clips:edit` scope, so run `/twitch auth` again if you authorized before it was added.

Two safeguards end or renew long streams: a stream restarts after `twitch_restart_hours`, and a stream that shows the capture card's no-signal screen for `twitch_no_signal_stop_minutes` is stopped. You get a DM either way.

## Nintendo Switch macros

Macros are line-based sequences of controller inputs. On Discord, send a message containing the macro, then use its **Define Macro** context-menu action to save it. Start the message with `$name` on its own line; the remaining lines are the macro body. Names are case-insensitive, and spaces in names become underscores.

```text
$soft_reset
hold +
wait
tap A
```

Each body line describes one step. Buttons on the same line are pressed together; separate lines run in order. Supported button tokens are `a`, `b`, `x`, `y`, `l`, `r`, `zl`, `zr`, `ls`, `rs`, `^` (up), `v` (down), `<` (left), `>` (right), `+` (plus), `-` (minus), `h` (home), and `c` (capture). For Joycon Shoulder buttons, use `lsl`, `lsr`, `rsl`, and `rsr`, respectively. Button names are case-insensitive, even symbols and numbers (`6` and `.` are the same as `^` and `>`).

Use `tap`, `hold`, or `wait` before a step to set its timing: tap presses for 0.05 seconds, hold for 1 second, and wait sleeps for 1 second (doing nothing). Default presses use 0.15 seconds down and 0.15 seconds up. Custom timing can be set on the same line using uses `(DOWN,UP)` in seconds, such as `(1.33,0.25) Bv`. Add `noblock` to a step to make NXBT return without waiting for that press to finish.

Users also have the ability to call another saved macro by name in the body of another. For example, a line containing `soft_reset` runs the macro previously defined with the leading line `$soft_reset`. Use `/get_macro` to inspect a definition and `/queue_macro` to queue one for playback. The built-in `zoom` (double tap `Home` accessibility shortcut) and `cleanup` (return to the Change Grip/Order menu before disconnect) macros are available. Start a definition with `$!name` to replace an existing macro with that name.

Macro definitions persist in `macros.json` under the configured `drive_path`; without an enabled drive, definitions are NOT saved across restarts. Conditional steps use `scene ? true_macro : false_macro`; they wait up to one second for a matching video scene (see `cynthia/daemons/cv.py`), then run the selected macro. For example, `home ? cleanup : zoom` selects based on whether the Switch home screen was detected.

### Shifted tokens and name collisions

Macro names are matched as substrings of a line. A very short name such as `a` or `d` can collide with button tokens, so use descriptive names.

### Sample macros

`examples/macros/` includes sample shiny-hunting macros for Pokémon Brilliant Diamond and Shining Pearl: `mespirit`, `cresselia`, `shaymin`, `arceus` and `darkrai`, plus the helpers they call (`roamer_decide`, `encounter_roamer`, `try_close_bag`, `encounter_proceed`, `roamer_reroll`, `screen_record`, `pause` and `run_up_down`). Each file starts with its `$name` line. Paste each file's contents into Discord and use **Define Macro**. Define the helper macros before the target macro; saved definitions persist in the configured drive.

All conditional branches are included, including recursive helpers. `wait`,
`hold`, and `tap` are built-in timing keywords, not separate saved macros.
`zoom` and `cleanup` are registered automatically by the bot. To update an
already saved sample, change its first line from `$name` to `$!name` before
using **Define Macro**.

These macros need a working Switch capture feed and the CV daemon. In BDSP settings, set **Text Box** to style 22 for reliable scene matching. Save in front of the target with the game open, then leave the Switch at the **Change Grip/Order** menu.

Connect and start a hunt with the target name and matching macro name:

```text
/connect
/set_hunt Darkrai
/queue_macro darkrai
/unpause
```

Replace `Darkrai` and `darkrai` with your target and its macro name. The Mesprit macro is named `mespirit`. `cyclient` is optional; run it on your desktop to sync your Discord Rich Presence with the bot's detected game status.

The conditional steps use scenes such as `route_202`, `roamer`, `bdsp_bag` and `bdsp_run`, provided by the CV daemon.

## Music

`/music` plays YouTube audio in voice calls. The group is not global: it works in a server only after `music` is added to that server's `allowed_commands` (or the `global` block).

| Command | Does |
| --- | --- |
| `/music play <query>` | Queue a YouTube or YouTube Music link, a whole playlist or album link (up to 50 songs), or the closest YouTube match for the words given, and play it in your voice channel. With no query, resumes a paused song. |
| `/music search <query>` | Same lookup and queueing as `play`, for keyword searches. |
| `/music pause` | Pause the current song. |
| `/music skip` | Skip the current song. |
| `/music stop` | Stop playback and clear the queue; the bot stays in the channel. |
| `/music queue` | Show the current song and the next ten. |
| `/music clear` | Clear the queue; the current song keeps playing. |
| `/music pin <link> [query]` | Pin a link: searches resembling `query` (default: the song's title) play it before any search result. Pins are saved per server on the drive. |
| `/music pins` / `/music unpin <number>` | List the server's pins / remove one. |
| `/music join` / `/music leave` | Join your voice channel / stop and leave. |

Searches rank YouTube results by title match, YouTube Music membership, artist signals (`Artist - Title`, artist or Topic channels), views and song-like length, and avoid covers, remixes, live versions and long mixes unless the query asks for them.

Public videos and playlists need no login. For age-restricted or members-only videos and private playlists, export a Premium session's `cookies.txt` (Netscape format, e.g. with a browser extension) and set `YTDL_COOKIES_FILE` in `.env`; passwords are not supported or needed. Keep that file out of git.

Playback runs inside the bot process, because Discord voice connections cannot be shared with a daemon process. Control commands require you to be in the bot's voice channel. Direct links are loaded as single videos, and live streams cannot be queued. The queue holds up to 100 songs per server.

## Discord Rich Presence

`tools/cyclient.py` reads the bot's `/api/user_status` endpoint and publishes the detected game and hunt as Rich Presence through the Discord desktop app. The bot must be running, and the configured host must be reachable from the computer running `cyclient`.

Install the optional client dependencies from the repository root:

```bash
python -m pip install -e ".[cyclient]"
```

Set `CYNTHIA_HOSTNAME` to the hostname or IP address serving the bot, and set `CYNTHIA_PROTOCOL` to `https://` or `http://`. The same host and protocol are used for the status API and video-feed links.

Run `cyclient` on a desktop where the Discord client is open:

```bash
python tools/cyclient.py
```

The script uses the project's public application ID and its art assets by default. To use your own application, upload art in **Developer Portal > Your Application > Rich Presence > Art Assets**. Asset keys must match exactly:

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
| Other detected games or the Switch home screen | `nintendo_switch` |

On the Switch home screen, CV reads the selected game title and corrects recognized OCR variations before publishing status; this is game-title matching, not game-specific encounter detection.

## Local chat model

Cynthia can chat on Twitch through a local language model served by [Ollama](https://ollama.com). She reads chat, answers in chat or aloud on stream, remembers chatters and remarks on hunt events. The bot owner controls and tests her with the owner-only `/llm` commands.

### Setup

Install Ollama with the script from ollama.com, then pull the default model. Llama 3.2 3B uses about 2.5 GB of VRAM with the default 4,096-token context and runs fully on a 6 GB GPU next to OBS:

```bash
ollama pull llama3.2:3b
```

To keep only one model loaded and one request running at a time, add a systemd override with `sudo systemctl edit ollama`:

```ini
[Service]
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_KEEP_ALIVE=30m"
```

She reads the channel in `TWITCH_CHANNEL` and posts with the Twitch authorization. To post under a separate bot username:

1. Create a Twitch account for the bot.
2. Run `/twitch botauth` in an owner DM.
3. Open its approval link in a private browser window and sign in as **the bot account**.

The same developer application is used, so no second Client ID is needed. `/twitch auth` still authorizes your broadcaster account for titles, categories and clips. Bot tokens are stored separately in `twitch_chat_token.json` in the bot's working directory.

Once the bot account is authorized, it is always used for chat, and replies still go to your channel. If its authorization lapses, posting fails visibly in `/llm log` instead of falling back to the broadcaster.

### Commands

| Command | Purpose |
| --- | --- |
| `/llm switch [name] [enabled]` | Show or flip the switches: `listen` (read chat), `learn` (chatter memory), `speak` (post in chat), `events` (spontaneous event and idle comments, off by default), `voice` (speak on stream) and `talk` (plain owner DMs). `all` turns everything off in one go; turning it back on restores each switch's own setting |
| `/llm say` / `event` / `trigger` / `moderate` | Test a chat message through the whole pipeline, have her remark on a stream event, check whether a message would get a reply, or check text against the filter |
| `/llm state` / `chat` / `log` / `filtered` | Show her live readout, the recent chat she sees, her recent decisions, or replies the filters blocked |
| `/llm prompt [default]` / `context` | Edit the persona (or restore the built-in one), or the notes added under it |
| `/llm show` / `sysprompt` | Show the persona, notes and switches, or attach the full system prompt she'd get right now |
| `/llm memory` / `memories` / `learn` | View and edit what she remembers about a chatter, list remembered chatters, or update a chatter's notes now |
| `/llm teach` / `lessons` / `unlearn` | Teach her lessons in conversation, list them, or remove one |
| `/llm tts` / `voices` / `setvoice` | Hear text in her voice, list Piper voices, or pick one |
| `/llm reset` / `status` | Clear the `/llm say` test conversation, or check Ollama and its GPU memory |

Prompt and note edits are saved to `config.yaml` when the bot shuts down.

### When she replies

Each chat message has a chance of a reply, by kind:

- **Mention:** naming Cynthia (including "Cynthia's", small typos and her full `@Cynthia__Bot` tag) or replying to her. Mentions are always answered.
- **Followup:** a question from someone she answered in the last `llm_followup_seconds`. Followups are always answered too.
- **Question, short message or other message:** answered by chance.

Mentions and followups that arrive during her pause between replies are answered when the pause ends. The streamer skips every cooldown, and her questions are always answered unless they're aimed at someone else. Messages aimed at someone else (an @name, a reply, or opening with a chatter's name) get no boosts.

Hard caps limit how chatty she gets, whoever she's answering. With `/llm switch name:events enabled:true`, stream events (shiny, encounter, watchdog, failsafe) and long silences get remarks by their own chances. This switch defaults to off and does not change replies to Twitch chat. Event remarks still need `speak` or `voice` enabled; `/llm event` remains available for manual tests.

Wrap a chat message in parentheses, like `(she's still learning)`, to talk without Cynthia hearing it. An unclosed `(…` or fullwidth `（…）` counts too. A parenthesized part inside a message, like `good bot (she's trying)`, is cut out before she reads it.

Replies are moderated (TOS, profanity, slurs, sexual content, personal info, links and repetition), run one at a time, and are trimmed to Twitch's 500-character limit. A reply is regenerated (up to 3 tries) if it:

- breaks a filter;
- talks about the person she's answering in the third person;
- says the streamer said, did or wants anything;
- doubts what the streamer said;
- fuses a name with other text.

The owner is DMed about safety blocks, with buttons to allow words or make a lesson.

### Who she knows

- **The streamer is trusted.** The streamer's lines are marked `(streamer, mom)`, and Cynthia knows the streamer, her creator and "mom" are one person talking to her directly. She answers her as "you" and takes what she says as true, and the profanity flag never hides her messages. A viewer's "mom said…" is marked unverified.
- **Chatter memory.** Notes about a chatter come only from their own first-person statements (not opinions, questions or requests), backed by their exact words. Things a chatter says about someone else are kept as unconfirmed hearsay: 15% confidence per different person saying it, capped at 60%, and shown to her as possibly a joke.
- **Pronouns.** She uses they/them unless a chatter states their pronouns ("my pronouns are she/her", "(he/him)"), or at least 3 messages from 2 or more people clearly about them agree.
- **Nicknames.** Nicknames chat uses ("fishy" for fish_vtuber) are learned after 3 uses.
- **Tone.** She keeps a slow-moving sense of how a chatter treats her.

`/llm memory` shows everything she knows about a chatter, including each pronoun clue.

Her stream readout spells out what each stat means. It separates her own uptime from the stream's and the total hunt time, defines a try, and gives both odds (no shiny yet, and one found by now) with how lucky that is.

### Chat journal

Every chat message she reads is journaled to `chat_journal/YYYY-MM-DD.jsonl` on the drive, one JSON object per line. Each entry records why she answered or skipped the message: its kind, the odds and roll, or the skip reason. Answered messages also record the exact prompt, every draft (including blocked ones) and the reply. Use the journal to tune the prompt and chances.

### Settings

| Setting | Default | Purpose |
| --- | --- | --- |
| `llm_url` / `llm_model` | `http://127.0.0.1:11434` / `llama3.2:3b` | Ollama server and model |
| `llm_enabled` | `true` | Master switch; `false` turns every switch below off |
| `llm_listen` / `llm_learn` / `llm_speak` / `llm_voice` / `llm_owner_talk` | `true` / `true` / `false` / `false` / `false` | The `/llm switch` switches |
| `llm_speak_offline` | `false` | Also talk while the stream is offline |
| `llm_system_prompt` / `llm_context` | empty | Persona (empty uses the built-in one) and notes added under it |
| `llm_context_messages` | `8` | Chat lines before the message being answered |
| `llm_bot_names` | `[cynthia]` | Names that count as talking to her (her account's login also counts) |
| `llm_ignored_chatters` | StreamElements, Nightbot, Streamlabs, Moobot | Chatters never read or answered |
| `llm_reply_<kind>_chance` | mention `1.0`, followup `1.0`, question `0.5`, short `0.03`, random `0.05` | Chance to answer each kind of message |
| `llm_followup_seconds` | `90` | How long after she answers someone their questions count as followups |
| `llm_quiet_window_seconds` / `llm_busy_chatters` | `180` / `5` | Chances rise towards certain the fewer people chatted in the window: fully with one, not at all with `llm_busy_chatters` or more. Short messages (under 4 words) get no rise |
| `llm_silence_boost_seconds` | `900` | Chances also rise the longer she has been silent, fully after this long; `0` turns it off |
| `llm_streamer_question_chance` | `1.0` | Chance of answering the streamer's questions, even without her name |
| `llm_streamer_boost` | `0.15` | Small extra lift for the streamer's longer messages |
| `llm_reply_min_seconds` / `llm_reply_jitter_seconds` | `9` / `2.5` | Pause between any two replies, drawn from a bell curve with this mean and spread (kept within ⅓–3× the mean) |
| `llm_reply_cooldown_seconds` | `30` | Cooldown before answering messages that don't name her |
| `llm_user_cooldown_seconds` / `llm_mention_cooldown_seconds` | `20` / `5` | Per-chatter cooldown, shorter when they name her |
| `llm_max_posts_per_minute` / `llm_max_posts_per_10_minutes` | `4` / `20` | Hard caps on her posts, including event and idle remarks (shiny news is exempt); `0` turns a cap off |
| `llm_mention_window_seconds` / `llm_mention_spam_free` / `llm_mention_spam_factor` | `60` / `2` / `0.5` | Each mention in the window past the first `llm_mention_spam_free` multiplies the chance of answering the next one; the streamer's don't count |
| `llm_repeat_similarity` | `0.8` | How alike (0–1) two messages must be to count as a repeat |
| `llm_repeat_input_factor` | `0.3` | Answer chance kept per repeat of a chat message she already answered |
| `llm_repeat_allow_chance` | `0.2` | Chance a reply close to one said lately still goes out (per repeat); phrase loops are always blocked |
| `llm_event_<kind>_chance` / `llm_event_cooldown_seconds` | shiny `1.0`, watchdog `0.75`, failsafe `0.5`, encounter `0.05`, idle `1.0` / `60` | Chance to remark on each stream event, and the cooldown between remarks |
| `llm_idle_minutes` | `20` | Minutes of silence before an idle remark |
| `llm_allowed_words` / `llm_blocked_words` | `[]` | Words to let through or add to the profanity list, for chat and Cynthia alike; a list or a comma-separated `/cset` value |
| `llm_notify_filtered` / `llm_notify_seconds` | `true` / `60` | DM the owner about blocked replies, at most this often |
| `llm_memory_batch` / `llm_memory_idle_minutes` | `6` / `15` | Update a chatter's notes after this many new messages, or once they go quiet |
| `llm_max_tokens` / `llm_temperature` / `llm_num_ctx` | `80` / `0.85` / `4096` | Reply length limit, variety, and context window (larger uses more VRAM) |
| `tts_voice` / `tts_loudness` | `en_US-amy-medium` / `-20` | Piper voice, and the level in dBFS every voice is normalized to |

The voice plays through an OBS "Cynthia Voice" source, so it's on stream but not in the WebRTC viewer.

## Tools

- `tools/scene_setup.html`: open it in a browser to crop a capture frame and generate scene parameters to edit and add your own to the CV daemon.

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
