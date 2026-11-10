# Operations

This guide covers routine operation of a running bot. See
[getting started](getting-started.md) for installing dependencies and creating
runtime files, and [streaming](streaming.md) for OBS-specific setup.

## Starting and stopping

Run Cynthia from the repository root so it finds `.env`, `config.yaml`, and
`perms.yaml`:

```bash
bin/run.sh --config config.yaml --perms perms.yaml
```

The wrapper starts `env/bin/cynthia` with `sudo` and restarts the process for
most nonzero exit statuses. Exit statuses 0 and 1 stop the loop. Its `-v`
option prints macro steps in the terminal; the full log is written to the
drive when logging is enabled.

Use `/shutdown` to stop the bot cleanly. The bot saves configuration and
permissions on exit and stops its managed daemons. `/restart` exits through
the wrapper so the bot can start again. `/reboot` requests a host reboot.
These lifecycle commands are privileged and some control commands are only
available in owner DMs. Check Discord command access and bot permissions before
relying on them.

`bin/install.sh` refreshes installed package metadata after a version change
without changing dependencies. Restart the running process after installing:
daemons and code already in memory do not change merely because files on disk
were updated. `/about` and OBS version watermark use startup version
information. The version display marks an unreleased checkout with `-alpha`
when Cynthia source/package files are modified or the checkout is not on
`origin/master`; this is evaluated at startup against the local ref, so fetch
the upstream branch before using it as a release check.

## systemd and tmux example

`deploy/` provides sample systemd and tmux files. The service starts the bot in
tmux and opens a second window for headless OBS:

| File | Destination | Purpose |
| --- | --- | --- |
| `deploy/cynthia.service` | `/etc/systemd/system/` | Starts the configured systemd service. Set its `User=`. |
| `deploy/cynthia.sh` | `/usr/local/bin/` | Creates the tmux session and selects the checkout via `CYNTHIA_DIR`. |
| `deploy/99-elgato-capture.rules` | `/etc/udev/rules.d/` | Optional capture-card access rule. |

Review and edit the examples for the actual service account and checkout path
before installing them. A typical setup is:

```bash
sudo cp deploy/cynthia.service /etc/systemd/system/
sudo install -m 755 deploy/cynthia.sh /usr/local/bin/cynthia.sh
sudo systemctl daemon-reload
sudo systemctl enable --now cynthia.service
tmux attach -t cynthia
```

`tmux` is optional if you run the bot another way. `bin/obs.sh` runs OBS
headless and is used by the sample script; its NVIDIA Xorg path requires the
provided headless configuration and noninteractive `sudo`, and it falls back
to Xvfb/software rendering.

## Publishing the documentation site

The homepage and documentation builder belong to the separate
`serenegrace.io` project. Cynthia owns the Markdown source in `docs/**`, but
its FastAPI service does not render or host the documentation. The website
project owns the builder, assets, renderer dependency, tests, and deployment
configuration.

```bash
cd /srv/usr/serenegrace.io
```

Build the homepage and documentation from the website checkout, pointing the
builder at the Cynthia checkout. This example reuses Cynthia's Python
environment; substitute the checkout paths as appropriate on another host:

```bash
/srv/usr/cynthia/env/bin/python tools/build_site.py \
  --cynthia-root /srv/usr/cynthia \
  --output build/site
```

The builder reads Cynthia's `docs/**` plus the website project's static
assets, then emits extensionless documentation URLs such as
`/docs/cynthia/getting-started/`. Install the Markdown renderer dependency in
the website project's environment from its `requirements.txt`; it is not a
Cynthia package extra. Treat `build/site` as disposable generated output, not
as the documentation source or a directory to commit. Rebuilds clean only a
marked generated-output directory; do not use an output path that contains
source files or other data. Review the generated site before publishing it.

The static build does not contain Cynthia's `/video_feed` viewer. That page
and its required frontend assets remain part of Cynthia, with
`cynthia/site/html/video_feed.html` as the canonical template; the route is
served by the bot's FastAPI service and needs its own reverse-proxy routing if
made public.

The web root is `/var/www/serenegrace.io`. The public homepage is `/`, and the
documentation is served at
[`https://serenegrace.io/docs/cynthia/`](https://serenegrace.io/docs/cynthia/).
Nginx serves the homepage, `/assets/`, and documentation files directly.
`/docs/cynthia` redirects to `/docs/cynthia/`. Publish the generated output to
the configured web root using the website project's approved deployment
process. Keep the bot's local port-8000 APIs and the static homepage/docs
deployment independent.

For the current deployment, nginx is enabled and active and its configured
document root persists. Nginx serves the static homepage and docs directly;
no separate website app daemon or running Cynthia bot is needed to serve those
files. The homepage's optional live ribbon API is a separate integration. No
host reboot was performed for the static-site deployment.

## Health and logs

- Owner `/status` checks the configured `status_services`, configured
  `STATUS_HOSTS` (or its default hosts), and drive availability.
- `/cynx status` checks the companion Pi separately; see
  [CyNX diagnostics](cynx.md#troubleshooting).
- `systemctl status cynthia.service` shows service state.
- `journalctl -u cynthia.service -n 100 --no-pager` shows service output.
- `tmux attach -t cynthia` shows the sample deployment's windows.
- The drive's `cynthia.log` and rotated siblings include detailed process logs
  and, when verbose logging is enabled, macro steps.

The manager monitors daemon health, restarts selected capture/CV processes
after exits or stalls, and detects an unchanged capture image while frames
continue arriving. It resets the capture daemon, which uses `usbreset` when
`ELGATO_USB_ID` is configured. Repeated recovery failures increase the delay
between attempts and notify the owner. The UVC capture daemon and computer
vision daemon have separate liveness checks.

## Hardware checks

| Component | Check |
| --- | --- |
| Bluetooth adapter | `bluetoothctl list`, `hciconfig` |
| Capture card | `lsusb`, `v4l2-ctl --list-devices` |
| User groups | `id` |
| Pi controller | `/cynx status` |

The capture card normally appears as `/dev/video*`. For the listed Elgato
capture devices, `deploy/99-elgato-capture.rules` grants the `plugdev` group
access. Install it only after confirming the hardware IDs it covers; reload
udev rules and re-login after changing group membership. `ELGATO_USB_ID` is
the `vendor:product` pair shown by `lsusb`, not a GUID.

```bash
sudo cp deploy/99-elgato-capture.rules /etc/udev/rules.d/
sudo udevadm control --reload
sudo udevadm trigger
```

Add the service user to the required groups for the host setup (commonly
`video`, `plugdev`, and `bluetooth`) and log in again so the group change takes
effect. At startup, Cynthia runs `usbreset` for the configured
`ELGATO_USB_ID`; leave it empty to skip reset.

NXBT writes a runtime systemd drop-in at
`/run/systemd/system/bluetooth.service.d/nxbt.conf` to run `bluetoothd` with
compatibility options, then restarts Bluetooth. This may disconnect other
Bluetooth devices while the bot runs. The drop-in is under `/run`; the stock
`/etc/bluetooth` files are not changed permanently.

## Privacy and security

- Keep `.env`, Twitch token files, YouTube cookies, and any shared controller
  passphrase in the working directory with restrictive file permissions.
- Do not upload secrets to the drive. The drive is for application state, not
  credentials.
- Keep the control host and companion Pi on a trusted LAN. Do not expose
  CyNX command or macro listeners to the Internet; its optional passphrase is
  not encryption.
- `bin/run.sh` runs as root through `sudo` for NXBT. Treat shell commands and
  host lifecycle controls as privileged capabilities, and grant command
  permissions only to trusted users.
- The local API and video viewer should be published only behind an
  appropriately configured reverse proxy and network policy. Review the
  [API guide](development.md#http-api-and-streamelements) before exposing it.

## Common failures

| Symptom | Checks |
| --- | --- |
| Bot exits at startup | Confirm `.env`, `config.yaml`, and `perms.yaml` exist; check the Python version and service log. |
| Slash command missing | Check startup sync logs, guild `allowed_commands`, Discord permissions, and any command-specific privilege check. |
| Macros are not saved | Check that `drive_path` or `DRIVE_PATH` points to a writable directory and the drive is enabled. |
| Bluetooth does not pair | Open Change Grip/Order on the Switch, check adapter state and other Bluetooth users, and consult the [NXBT fork](https://github.com/serenagrace/nxbt). |
| No capture video | Check the device with `v4l2-ctl`, user access, cables, and the UVC daemon log. |
| OBS feed is absent | Confirm OBS is open (unless `obs_feed: always`), the configured UDP port matches, and the host has an NVIDIA GPU and `ffmpeg` with `h264_nvenc`. |
| Music cannot play | Check the bot is in the caller's voice channel, the command is enabled, and FFmpeg/Opus are installed. |

For Switch and macro behavior see [Switch control](switch-control.md); for
stream output see [Video, OBS, and Twitch](streaming.md).
