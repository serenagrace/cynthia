# Video, OBS, and Twitch

Cynthia can publish a browser video feed, send a separate OBS feed, and
optionally automate Twitch metadata and clips. These functions require a
working capture card; OBS/Twitch additionally require their own software and
credentials.

## Browser video

The viewer is available at [serenegrace.io/video_feed](https://serenegrace.io/video_feed).
That route is served by Cynthia's local FastAPI service, whose canonical
viewer template and required frontend assets ship with Cynthia at
`cynthia/site/html/video_feed.html` and its bundled site files; it is
independent of the static homepage/docs project. The service provides WebRTC
when `mediamtx` is on `PATH`, with an MJPEG fallback. For viewers outside the
host LAN, configure `webrtc_hosts` and forward the configured WebRTC media
port over UDP and TCP; see the example configuration. Network access should
be limited to intended viewers.

`web_fps` and `web_height` set the browser stream mode. `/webstream framerate`
and `/webstream resolution` can change it live. CV processing is capped at
30 fps. The capture card uses a mode sufficient for active consumers rather
than always running at the maximum resolution.

## OBS feed and scene

When OBS is open, the OBS daemon encodes H.264 video using FFmpeg's NVENC
encoder and sends MPEG-TS over UDP to `127.0.0.1:5000` by default. Capture-card
audio is included. This requires an NVIDIA GPU and an FFmpeg build with
`h264_nvenc`. Set `obs_feed: always` to send when OBS is closed, or `false` to
disable this feed. `obs_feed_port`, `obs_fps`, and `obs_height` configure the
endpoint.

Import `deploy/obs/Cynthia.json` into OBS or create a Media Source using:

```text
udp://127.0.0.1:5000?overrun_nonfatal=1&fifo_size=5000000&buffer_size=4194304
```

Set the input format to `mpegts`. The large buffer avoids packet drops and
stutter on a busy feed. The bot manages OBS through obs-websocket; configure
`OBS_WS_HOST`, `OBS_WS_PORT`, and `OBS_WS_PASSWORD` in `.env`. `/obs` controls
framerate, resolution, recording, and layout; `/webstream` controls the browser
stream independently.

The layout is read from `obs_layout.yaml` (copy
`obs_layout.example.yaml`). It can include game video, input visualizer, scene
scores, hunt statistics, Twitch chat, and a version watermark. Browser
overlay panes require OBS's browser-source plugin. `bin/obs.sh` supplies the
optional headless OBS launch used in the sample deployment.

## Feed recovery and overlay timing

OBS and WebRTC monitor fresh-frame throughput. After a startup grace period,
repeated slow windows recycle the affected encoder; a brief interruption does
not restart the bot or its macros. Stalled daemon processes are monitored
separately. Capture freeze recovery is covered in
[operations](operations.md#health-and-logs).

The overlay synchronization cog compares the OBS-displayed video against
recent capture thumbnails while OBS is streaming or recording. Consistent
matches gradually adjust the input and scene overlay delay. It does not change
the WebRTC delay or OBS's internal video buffer. Ambiguous or static scenes
retain the last measured delay; disconnects and source restarts fall back to
configured values.

| Setting | Default | Purpose |
| --- | --- | --- |
| `obs_auto_sync` | `true` | Measure video age and adjust overlay timing automatically. |
| `obs_feed_delay_ms` | `1000` | Fixed holdback for the OBS feed. |
| `obs_overlay_lag_ms` | `1700` | Additional fallback delay for overlays. |
| `stream_delay_ms` | `1000` | Browser video holdback for smoother audio. |

`/api/stream_stats` reports effective stream and overlay measurements. A
custom `?lag=<ms>` on the OBS input pane is a separate delay; remove manual
tuning when using measured synchronization. A restart is required to activate
updated daemon code after a package update.

## Twitch streaming

Set `TWITCH_STREAM_KEY` or `OBS_STREAM_KEY` for streaming. The Twitch key takes
precedence. Owner-only `/twitch start`, `stop`, `test`, `uptime`, and `status`
commands control and inspect the broadcast. Starting and stopping use a
confirmation button. `test` runs Twitch bandwidth-test mode rather than going
live. `/twitchurl` shares the configured channel URL and live status.

Optional safeguards are controlled by:

| Setting | Default | Effect |
| --- | --- | --- |
| `twitch_bitrate_kbps` | `6000` | OBS Simple-mode output bitrate. |
| `twitch_restart_hours` | `24` | Restart long broadcasts; `0` disables. |
| `twitch_no_signal_stop_minutes` | `10` | Stop after prolonged capture no-signal; `0` disables. |
| `capture_freeze_seconds` | `120` | Reset a capture card whose image freezes while frames continue; `0` disables. |
| `twitch_reboot_message` | Fixed text | Message sent on restart/reboot while streaming; empty disables. |
| `twitch_goodbye_message` | Fixed text | Message before shutdown ends the stream; empty skips the message. |

## Twitch authorization, metadata, and clips

To set titles/categories and create clips:

1. Register a Twitch application and configure `TWITCH_CLIENT_ID`; add
   `TWITCH_CLIENT_SECRET` if it is a confidential client.
2. Restart Cynthia, then run owner-only `/twitch auth` and approve the
   requested scopes.
3. Keep `twitch_token.json` in the bot's working directory, not on the drive.
   Protect it as a credential.

If upgrading from a Cynthia release that stored Twitch tokens on the drive,
stop the bot before moving `twitch_token.json` and `twitch_chat_token.json` (if
present) into the working directory. Do not overwrite an existing token file;
resolve duplicates before restarting. Restrict token file permissions to the
bot account. A rollback to a version that expects drive-stored tokens requires
moving the files back.

The bot changes title/category after a recognized game or hunt remains stable
for `twitch_info_confirm_seconds` (default 60 seconds). `twitch_auto_info`
enables this behavior, and `twitch_categories` maps game titles to category
names or IDs when Twitch uses a different name. The previously applied pair is
recorded in `twitch_channel.json`, so a restart does not reapply it. The bot
does not continuously overwrite manual Twitch edits.

When the hunt's possible-shiny stop fires, `twitch_auto_clip` can create a
30-second clip after the event reaches the delayed Twitch feed. The delay uses
the effective OBS overlay delay plus `twitch_clip_delay_seconds` (default 10
seconds). Clipping requires the `clips:edit` scope; authorize again if that
scope was not approved.

Twitch chat overlay messages can be cleared from the pane with owner-only
`/twitch clearchat`. This affects the displayed pane, not Twitch chat or the
local model's memory. See [local chat](local-chat.md) for optional chat
generation and separate bot-account authorization.

## Access and proxying

The local web service hosts the viewer and API. Do not expose it directly
without a reverse proxy and access controls. If proxying, preserve streaming
and WebRTC transport behavior and allow the endpoints listed in
[the API guide](development.md#http-api-and-streamelements). `webrtc_hosts`
advertises public viewer hosts; it does not replace firewall or proxy
configuration.
