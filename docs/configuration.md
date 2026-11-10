# Configuration reference

The complete default mapping is in [`config.example.yaml`](../config.example.yaml);
the default values are defined in `cynthia/context/defaults.py`. This page
explains the common runtime settings by purpose. Environment variables and
permissions are described in [getting started](getting-started.md).

## General and host settings

| Key | Default | Description |
| --- | --- | --- |
| `debug` | `false` | Debug configuration flag. |
| `silent` | `false` | Send ordinary Discord responses silently where supported; alerts remain visible. |
| `owner` | unset | Discord user ID used for owner checks and notifications. Set this in `config.yaml`. |
| `drive_path` | unset | Directory for persistent state. `DRIVE_PATH` in `.env` overrides it; `null` disables drive-backed features. |
| `status_services` | `[cynthia.service]` | systemd units checked by owner `/status`. |
| `encounter_reset` | `true` | Restart the looping hunt macro five seconds after an encounter unless a shiny stop has fired. |
| `obs_scene` | `Cynthia` | Name of the OBS scene managed by the bot. |
| `obs_layout_file` | `obs_layout.yaml` | OBS browser-source and media layout description. Copy `obs_layout.example.yaml` before customizing it. |

`/status` also pings hosts from `STATUS_HOSTS` in `.env`; if unset, it checks
`discord.com`, `github.com`, and `google.com`. The command's service checks
require `systemctl` and a compatible host environment.

Add the Pi's actual hostname to `STATUS_HOSTS` for reachability checks,
while retaining any existing hosts. For this deployment, static-site health is
checked through `nginx.service` in `status_services`; nginx serves the static
site independently, so no separate website service unit is needed. Retain
existing service entries when adding `nginx.service`.

## Wired controller discovery

These settings are used by Cynthia's CyNX daemon; ports must match the
companion service configuration. See [CyNX](cynx.md) for network,
authentication, and recovery details.

| Key | Default | Description |
| --- | --- | --- |
| `cynx_enabled` | `true` | Enable automatic Pi discovery and status monitoring. |
| `cynx_auto_connect` | `true` | Connect USB automatically at startup. Set `false` to require manual connect; discovery/status remain available. |
| `cynx_command_port` | `3140` | TCP command/heartbeat port and UDP discovery port. |
| `cynx_macro_port` | `3141` | TCP macro-step channel. |
| `cynx_heartbeat_interval` | `1.0` | Delay between status heartbeats. Keep below the service heartbeat timeout. |
| `cynx_discovery_timeout` | `1.0` | Wait interval for a discovery response, in seconds. |
| `cynx_discovery_interval` | `2.0` | Delay between discovery attempts, in seconds. |

The optional `CYNX_PASSPHRASE` is an environment variable, not a YAML key.
Configure it in both working-directory `.env` files; a blank value on both
ends disables authentication. It must not be stored on the drive.

## Capture, web, and OBS video

| Key | Default | Description |
| --- | --- | --- |
| `obs_feed` | `true` | Send an OBS video feed while OBS is running. Use `"always"` to send continuously or `false` to disable. |
| `obs_feed_port` | `5000` | Local UDP port receiving OBS's MPEG-TS feed. |
| `obs_feed_bitrate` | `50M` | FFmpeg H.264 bitrate for the OBS feed. |
| `obs_fps`, `obs_height` | `60`, `1080` | OBS output frame rate and height. Supported rates are 15, 24, 30, and 60 fps; heights are 480, 720, and 1080. |
| `web_fps`, `web_height` | `30`, `720` | Browser stream frame rate and height. CV remains capped at 30 fps. |
| `webrtc` | `true` | Enable WebRTC output when MediaMTX is available; the page falls back to MJPEG. |
| `webrtc_port` | `8889` | WebRTC web/signaling port. |
| `webrtc_media_port` | `8189` | WebRTC media port; forward TCP and UDP for off-LAN viewers. |
| `webrtc_api_port` | `9997` | MediaMTX API port used by the local service. |
| `webrtc_ingest_port` | `5100` | Local ingest port used by the stream pipeline. |
| `webrtc_bitrate` | `8M` | WebRTC encoder bitrate. |
| `webrtc_hosts` | `[]` | Public hostname/IP values advertised to remote viewers. |
| `stream_delay_ms` | `1000` | Browser-video holdback used to smooth the video/audio path. |

For OBS timing:

| Key | Default | Description |
| --- | --- | --- |
| `obs_auto_sync` | `true` | Measure OBS video age and adjust overlay timing when frame matches are reliable. |
| `obs_feed_delay_ms` | `1000` | Fixed holdback applied to OBS audio/video. |
| `obs_overlay_lag_ms` | `1700` | Additional fallback delay for OBS input and scene overlays. |

OBS sync adjusts overlay timing, not OBS's internal video buffer. See
[streaming](streaming.md#feed-recovery-and-overlay-timing) for automatic
measurement, fallback behavior, and troubleshooting.

## Twitch safeguards and metadata

The stream key, channel name, and Twitch application credentials are
environment variables; see [getting started](getting-started.md#environment-variables).
The following YAML keys control behavior:

| Key | Default | Description |
| --- | --- | --- |
| `twitch_bitrate_kbps` | `6000` | Twitch OBS output bitrate, in kilobits per second. |
| `twitch_restart_hours` | `24` | Stop and restart long streams before Twitch's broadcast limit; `0` disables. |
| `twitch_no_signal_stop_minutes` | `10` | Stop the broadcast after capture remains on the no-signal screen this long; `0` disables. |
| `capture_freeze_seconds` | `120` | Reset a capture card whose image remains frozen while frames continue; `0` disables. Repeated failed recovery attempts wait longer. |
| `twitch_reboot_message` | Fixed message | Chat message sent during `/restart` and `/reboot` if streaming; empty disables it. |
| `twitch_goodbye_message` | Fixed message | Message sent on `/shutdown` before ending the stream; empty skips the message. |
| `twitch_auto_clip` | `true` | Create a clip when the shiny stop fires; requires Twitch authorization. |
| `twitch_clip_delay_seconds` | `10` | Delay after the event reaches the delayed OBS overlay before requesting a clip. |
| `twitch_auto_info` | `true` | Set channel title/category from a stable, recognized game and hunt after authorization. |
| `twitch_info_confirm_seconds` | `60` | How long game/hunt state must remain stable before updating the channel. |
| `twitch_categories` | `{}` | Mapping from detected game title to a Twitch category name or ID. |
| `twitch_forward_chat` | `true` | DM viewer chat to the owner, live or offline. Toggle with owner-only `/twitch notifychat on:true` or `on:false`. |

See [streaming](streaming.md#twitch-authorization-metadata-and-clips) for
authorization, stored token files, title/category behavior, and clip scope.

## Local model and text-to-speech

The local model settings are listed in
[Local chat: configuration reference](local-chat.md#configuration-reference).
The important host settings are:

| Key | Default | Description |
| --- | --- | --- |
| `llm_url` | `http://127.0.0.1:11434` | Ollama server URL. |
| `llm_model` | `llama3.2:3b` | Model tag already available to Ollama. |
| `tts_voice` | `en_US-amy-medium` | Piper voice used by the OBS voice source. |
| `tts_loudness` | `-20` | Normalized voice output level in dBFS. |

## Editing and persistence

Configuration can also be edited with owner/admin `/cset` commands. Changes
made in memory and through configuration commands are saved when the process
exits. Back up `config.yaml` before broad changes. To make changes effective
for daemons or options loaded at startup, restart the bot after editing the
file. Keep secrets in `.env`, not in YAML configuration or drive-backed state.
