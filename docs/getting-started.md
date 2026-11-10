# Getting started

This guide installs Cynthia itself. Switch, capture, OBS, Twitch, and local AI
features are optional and have separate guides.

## Requirements

- Linux and Python `>=3.11,<3.12`.
- A Discord bot token. The bot requests the member and message-content intents;
  enable the intents it uses in the Discord Developer Portal.
- Root-capable host access for NXBT Bluetooth control. `bin/run.sh` invokes the
  bot with `sudo`.

The package's PaddleOCR/PaddlePaddle stack is supported here on Python 3.11;
Python 3.12+ is outside the declared package range. Capture and Switch control
also require their corresponding hardware, drivers, and system packages. The
optional local Ollama model is a separate service.

## Install

For Debian or Ubuntu, the common system packages are:

```bash
sudo apt install bluez v4l-utils usbutils tmux ffmpeg libopus0
```

Add `obs-studio xvfb` for the headless OBS example. NXBT also needs the
Bluetooth compatibility utilities `hciconfig`, `hcitool`, and `sdptool`; on
Arch these are provided by `bluez-deprecated-tools`. On Arch, install the
corresponding packages with:

```bash
sudo pacman -S bluez bluez-utils bluez-deprecated-tools v4l-utils usbutils tmux ffmpeg opus
sudo systemctl enable --now bluetooth.service
```

For headless OBS on Arch, add `obs-studio`, `obs-studio-plugin-browser`, and
`xorg-server-xvfb`. Arch's official repositories may not provide Python 3.11;
if using an AUR package such as `python311`, review its build files and use
`python3.11` for the environment. The video capture stack
uses `v4l2-ctl`, and Discord voice playback uses FFmpeg and Opus. `tmux` is
needed only for the sample boot-time deployment.

Create the virtual environment named `env` (the run and deployment scripts
expect that name) and select exactly one Paddle build:

```bash
python3.11 -m venv env
source env/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[cpu]"
```

On an NVIDIA host with a CUDA 12.6-compatible driver, use the GPU wheel instead:

```bash
python -m pip install -e ".[gpu]" \
  --extra-index-url https://www.paddlepaddle.org.cn/packages/stable/cu126/
```

Do not install both `cpu` and `gpu`. To switch an existing environment,
uninstall its current Paddle package before installing the other extra. The
bot can use GPU OCR with the GPU build and otherwise runs on CPU.

### Optional Python packages

Run these commands from the Cynthia checkout with `env` activated. Extras
install Python packages, not operating-system programs or model weights.

| Extra | Packages added | Install |
| --- | --- | --- |
| `cpu` | CPU PaddlePaddle OCR runtime | `python -m pip install -e ".[cpu]"` |
| `gpu` | CUDA PaddlePaddle OCR runtime | Use the GPU command above, including Paddle's CUDA index. |
| `dev` | Black, isort, pytest, and build | `python -m pip install -e ".[dev]"` |
| `cyclient` | pypresence and requests for desktop Discord Rich Presence | `python -m pip install -e ".[cyclient]"` |

Choose one OCR runtime, even when adding other extras. For a fresh CPU
development environment with Rich Presence, install them together:

```bash
python -m pip install -e ".[cpu,dev,cyclient]"
```

`cyclient` runs on the machine with Discord desktop, which may differ from
the bot host. To avoid installing the full Python 3.11 bot stack there,
install only its two dependencies and run the standalone script:

```bash
python3 -m venv client-env
client-env/bin/python -m pip install pypresence requests
client-env/bin/python tools/cyclient.py
```

See [Rich Presence configuration](development.md#discord-rich-presence-client)
for the server address. The standalone script is not limited to Python 3.11.

### Optional system packages and services

Install only the rows needed for the features you use. These are separate
from `pip` extras.

| Feature | Debian / Ubuntu | Arch Linux |
| --- | --- | --- |
| Discord music and capture encoding | `sudo apt install ffmpeg libopus0` | `sudo pacman -S ffmpeg opus` |
| Capture-card inspection | `sudo apt install v4l-utils usbutils` | `sudo pacman -S v4l-utils usbutils` |
| OBS streaming and recording | `sudo apt install obs-studio` | `sudo pacman -S obs-studio obs-studio-plugin-browser` |
| Headless OBS display | `sudo apt install xvfb` | `sudo pacman -S xorg-server-xvfb` |
| Sample tmux deployment | `sudo apt install tmux` | `sudo pacman -S tmux` |

OBS needs its browser-source plugin for overlay panes and OBS 28+ for built-in
obs-websocket. Debian/Ubuntu OBS builds differ; if Browser Source is missing,
use an OBS distribution with browser support from the
[official OBS installation guide](https://obsproject.com/kb/linux-installation).
The OBS feed also needs an NVIDIA driver and FFmpeg's `h264_nvenc` encoder;
installing FFmpeg alone does not provide suitable hardware or drivers.

For optional WebRTC, install the `mediamtx` executable from the
[official MediaMTX releases](https://github.com/bluenviron/mediamtx/releases).
Download the Linux archive matching the host architecture, extract it, then
install the extracted binary:

```bash
sudo install -m 755 mediamtx /usr/local/bin/mediamtx
mediamtx --version
```

Cynthia starts and configures MediaMTX itself; do not start a second service
on its ports. Restart Cynthia after adding the executable. Without MediaMTX,
the viewer falls back to MJPEG. See [streaming](streaming.md) for ports.

Ollama is a separate optional service, not a Python extra; see the
[Ollama and voice installation commands](local-chat.md#install-ollama).
Piper TTS is already included in Cynthia's Python dependencies; selecting
and downloading a voice does not require another `pip` extra.
Wired Switch control instead requires the separate
[CyNX installation](https://github.com/serenagrace/cynx/blob/development/docs/installation.md)
on the Raspberry Pi, not on the Cynthia host.

## Runtime files

Copy the example configuration files:

```bash
cp .env.example .env
cp config.example.yaml config.yaml
cp perms.example.yaml perms.yaml
```

Keep the real files private. They are gitignored. The bot requires the config
and permissions files to exist, even if they contain only defaults. Cynthia
loads `.env` from its current working directory; real process environment
variables override values from that file.

### Environment variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `DISCORD_BOT_TOKEN` | Yes | Discord bot token. |
| `OTP_SECRET` | No | TOTP secret for owner verification; verification is disabled if unset. |
| `DRIVE_PATH` | No | Overrides `drive_path` in `config.yaml`. |
| `SYNC_GUILD_ID` | No | Also sync slash commands to this guild for faster updates; global sync still occurs. |
| `STATUS_HOSTS` | No | Comma-separated hosts checked by owner `/status`; defaults to Discord, GitHub, and Google. |
| `ELGATO_USB_ID` | No | Capture card `vendor:product` ID for startup reset; empty disables reset. |
| `CYNX_PASSPHRASE` | No | Optional shared passphrase for [CyNX](cynx.md); never store it on the drive. |
| `OBS_WS_HOST`, `OBS_WS_PORT`, `OBS_WS_PASSWORD` | No | OBS WebSocket address and password; defaults to localhost port 4455. |
| `TWITCH_STREAM_KEY`, `OBS_STREAM_KEY` | No | Streaming key; `TWITCH_STREAM_KEY` takes precedence for `/twitch`. |
| `TWITCH_CHANNEL` | No | Twitch channel used by the viewer's chat pane and related commands. |
| `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET` | No | Twitch application credentials for broadcaster authorization. |
| `YTDL_COOKIES_FILE` | No | Optional browser-exported cookies for restricted YouTube videos. |

Never put tokens or passphrases on the drive. Twitch authorization tokens and
other local secrets belong in the bot's working directory; protect them from
source control and other system users.

### Configuration and permissions

Configuration values in `config.yaml` override `Context` defaults. Config is
read as a mapping and persisted, together with the permissions mapping, when
the process exits. `DRIVE_PATH`, if set, takes precedence over `drive_path`.
Use `drive_path: null` to disable drive-backed state.

Common settings include:

| Setting | Purpose |
| --- | --- |
| `owner` | Discord user ID used for owner-only commands and alerts. |
| `silent` | Send ordinary bot responses silently where supported; alerts remain visible. |
| `status_services` | systemd unit names checked by `/status`. |
| `encounter_reset` | Restart the looping hunt macro after a detected encounter; defaults to enabled. |
| `cynx_enabled`, `cynx_command_port`, `cynx_macro_port` | Enable and configure local CyNX discovery and connections; see [CyNX](cynx.md). |
| `obs_feed`, `obs_feed_port`, `obs_fps`, `obs_height` | Configure the OBS capture feed. |
| `web_fps`, `web_height`, `webrtc*`, `stream_delay_ms` | Configure the browser stream. CV remains capped at 30 fps. |
| `obs_layout_file`, `obs_auto_sync`, `obs_feed_delay_ms`, `obs_overlay_lag_ms` | Choose OBS layout and feed/overlay timing. |
| `twitch_*` | Configure stream bitrate, safeguards, clips, and game/hunt metadata. |
| `llm_*`, `tts_*` | Configure the optional Ollama chat persona and Piper voice; see [Local chat](local-chat.md). |

See the [configuration reference](configuration.md) for media, Twitch, and
health-monitor settings, and [local chat](local-chat.md) for the model. The
complete set of defaults and comments is in
[`config.example.yaml`](../config.example.yaml). Restart Cynthia after
changing settings that are read during startup.

Permission lists are defined per permission context in `perms.yaml`. Entry
syntax is `+u:<id>` / `-u:<id>` for users, `+r:<id>` / `-r:<id>` for roles,
and `+g:<id>` / `-g:<id>` for guilds. The `global` context applies everywhere;
a `g:<guild-id>` context is combined with it for that server. A deny overrides
an allow at the matching level. The configured owner is added to each
permission list except `allowed_commands`.

The permission keys in `perms.example.yaml` include `admins`, `allowed_commands`,
`drive`, `nxbt`, `owners`, and `privileged`. `allowed_commands` controls which
slash commands are available in guild contexts. Some commands additionally
require Discord permissions, a command-specific check, or owner access.

## Run

```bash
bin/run.sh --config config.yaml --perms perms.yaml
```

The script runs `sudo env/bin/cynthia` and restarts it for exit codes other
than 0 and 1. Use `-v` to also print each macro step. The bot discovers and
syncs slash commands on startup, loads cogs and daemons, and writes current
configuration and permissions back at shutdown.

The package entry point can also be run directly from the activated
environment:

```bash
cynthia --config config.yaml --perms perms.yaml
```

This bypasses the wrapper's restart loop and `sudo`; Bluetooth control may not
work unless the process is otherwise granted the required host privileges.

## Drive-backed state

When `drive_path` is enabled, Cynthia uses the directory for persistent
application state. Examples include:

- `macros.json`: saved Switch macros.
- `cynthia.db`: Discord logging and `OnMessage` rules.
- `cynthia.log` plus rotated logs: process and macro log output.
- `encounter_times.log`, `user_status.json`, `activity_stats.json`, and
  compressed message/access logs.
- `twitch_channel.json`: last applied Twitch game and hunt.
- `pokemonDB_dataset.csv`: optional species data for `/pokemon` and `/ev`.
- `compendium/` and `chat_journal/`: cached lookup data and optional chat
  journal.

Without a drive, drive-backed features such as saved macros, database
logging, and datasets are unavailable. Keep backups appropriate to your
privacy needs. Never put `.env`, Twitch token files, or authentication secrets
there.

## Dependency maintenance

The OCR dependencies are intentionally pinned and constrained as a compatible
set: PaddleOCR/PaddleX and PyYAML versions are coupled, and the current OpenCV
and NumPy ranges avoid a NumPy 2 migration. Before changing these requirements,
resolve dependencies, run the tests, and exercise OCR on the supported CPU and
GPU environments. See `pyproject.toml` and the repository's Dependabot
configuration for the active constraints.
