# Changelog

## 1.8.0

### Added

#### Chat model
- Cynthia can chat on Twitch through a local model (Ollama, Llama 3.2 3B, 4,096-token context, fully on the GPU). She reads chat and answers in chat, aloud on stream, or both. Her prompt includes:
  - the messages before the one she answers, and the chatter's earlier messages this stream;
  - memories of the chatter and anyone they name, and the names present in chat;
  - game, hunt, stream, bot and controller state;
  - Pokémon facts (legendaries, mythicals, types, regions, games) looked up from the game, the hunt target and chat.

  Prompts are trimmed to fit the context window.
- The stream readout spells out what each stat means: her own uptime versus the stream's and the total hunt time, and what a try is. It gives both odds (no shiny yet, and one found by now), how lucky that is, and the expected remaining tries.
- Owner-only `/llm` commands cover testing, memory viewing and editing, teaching, status and blocked replies. `/llm sysprompt` attaches the full system prompt she'd get right now. In talk mode, plain DMs to the bot teach her.
- `/llm switch` turns reading chat (`listen`), learning, posting (`speak`), `voice` and DM `talk` on and off; each is saved in the config. `all` (`llm_enabled`) turns everything off in one go, and turning it back on restores each switch's own setting.
- When she replies:
  - Replies are triggered by chance per message kind (mention, question, short, other) and per stream event (shiny, encounter, watchdog, failsafe, idle).
  - A mention is naming Cynthia (including "Cynthia's", small typos and her full `@Cynthia__Bot` tag) or replying to her. Mentions and followups are always answered. A followup is a question from someone she answered in the last `llm_followup_seconds` (`90`).
  - She waits a bell-curve pause between replies (about 9 s on average). Mentions and followups that arrive during it are answered when it ends.
  - Chances for other messages rise towards certain the quieter chat is (`llm_quiet_window_seconds`, `llm_busy_chatters`) and the longer she has been silent (`llm_silence_boost_seconds`). Short messages (under 4 words) get no rise and default to `0.03`.
  - Messages aimed at someone else get no boosts: an @name, a reply, or a message opening with a recent chatter's name.
  - The streamer skips every cooldown, and her questions are always answered (`llm_streamer_question_chance`).
  - Mentions past the first `llm_mention_spam_free` (`2`) in a minute are less likely to be answered, and so are repeats of chat she already answered.
  - Hard caps: at most `llm_max_posts_per_minute` (`4`) and `llm_max_posts_per_10_minutes` (`20`) posts, including event and idle remarks. Shiny news is exempt.
- Chat in parentheses, like `(she's still learning)`, is an aside she never hears. Unclosed `(…` and fullwidth `（…）` count too. Asides are stored and journaled, but never answered, used as context or learned from. Parenthesized parts inside a message are cut out before she reads it; pronouns like `(she/her)` are still noted.
- The streamer is trusted:
  - Her lines are marked `(streamer, mom)`, and Cynthia's own lines are marked `(you)`.
  - Cynthia knows the streamer, her creator and "mom" are one person talking to her directly. She answers her as "you" and takes what she says as true.
  - Viewers can't speak for the streamer: a viewer's "mom said…" is marked unverified, and things viewers say about the streamer are never shown to her as memory.
  - The streamer's messages are never hidden by the profanity flag.
- Moderation in and out: TOS, profanity, slurs, sexual content, personal info and links.
  - A repetition filter catches looping phrases and replies close to recent ones.
  - Blocked replies are retried with feedback, logged (`/llm filtered`) and DMed to the owner, with buttons to make a lesson or allow words.
  - `llm_allowed_words` and `llm_blocked_words` accept a comma-separated string, so `/cset` can set them.
- Replies are also checked for how they treat people, and regenerated (up to 3 tries, logged without a DM) when they:
  - talk about the person being answered in the third person;
  - say the streamer said, did or wants anything (even if true);
  - doubt or snark at what the streamer said ("nice try");
  - fuse a name with other text ("serenachannel").

  Speaker labels copied from the transcript are stripped.
- She recognizes her own chat posts and never answers them. Posts made as the broadcaster are matched by message ID or by normalized text.
- Chatter memory:
  - Notes come only from a chatter's own first-person statements, not opinions, questions or requests. Each fact must be backed by the chatter's exact words, which are kept when the model shortens it.
  - New facts are added to existing notes (including owner-added ones) instead of rewriting them. Each chatter is described by real counts (streams, messages, since when).
  - Facts about other chatters are asked about one message at a time, and kept as unconfirmed hearsay: 15% confidence per different person saying it, capped at 60%, and shown as possibly a joke.
  - Pronouns come from fixed patterns only: the chatter stating them, or at least 3 messages from 2 or more people clearly about them, with 80% using one set. Everyone else is they/them.
  - Nicknames are learned after 3 uses of a word that fuzzy-matches exactly one chatter in chat.
  - A slow-moving sense of how a chatter treats her comes from fixed word lists, applied to mentions of her and replies to her only.
- Chat journal: every Twitch chat message she reads is written to `chat_journal/YYYY-MM-DD.jsonl` on the drive. Each entry records the message kind, the reply odds and roll, or why she skipped it. For replies it also records the exact prompt, every draft (including blocked ones) and whether it was posted. Event remarks are journaled too.
- Piper text to speech on stream through an OBS "Cynthia Voice" source. Every voice is normalized to `tts_loudness` (-20 dBFS) with a soft peak limit. Choose voices with `/llm voices` and `/llm setvoice`. Clips play even when Cynthia runs as root and OBS runs as another user.

#### Twitch
- Separate chat identity: `/twitch botauth` authorizes a bot account for chat without replacing the broadcaster's tokens. Once a bot account is set up it is always used. If its authorization lapses, posting fails visibly in `/llm log` instead of falling back to the broadcaster.
- While streaming, `/restart` and `/reboot` post a fixed "be right back" message in Twitch chat (`twitch_reboot_message`). `/shutdown` posts a goodbye (`twitch_goodbye_message`), waits 5 seconds and ends the stream. Neither message comes from the chat model, and a blank message disables it.

#### Other
- Persistent log file: every process (the bot and its daemons) writes to `cynthia.log` on the drive, including macro steps, daemon crashes and uncaught errors. It rotates at 20 MB and keeps 10 old files.
- Unreleased builds show their version as `-alpha` (for example `1.8.0-alpha`) in the about embed and the OBS watermark. A build is unreleased when it has uncommitted changes to `cynthia/` or `pyproject.toml`, or its commit isn't on `origin/master`.

### Changed
- `/twitch` commands and `/twitchurl` use Twitch purple (`#9146FF`) for every embed and panel, instead of red or grey for live or offline.
- The default OBS watermark pane is wider (`x: 0.7, w: 0.3`), and its text shrinks to fit instead of being cut off.
- The scene-score panes (OBS overlay and web viewer) poll every 250 ms instead of every second, so they trail the video by up to a second less.
- Macro steps are shown on the console only with `-v`/`--verbose`. They made up nearly all of the console output and pushed errors out of the scrollback.

### Fixed
- The daemon monitor never ran. A second `setup_hook` replaced the one that started it, so dead or stalled capture and CV daemons were never restarted automatically. It now starts once commands are loaded.
- A capture card that keeps delivering frames of one frozen picture is now detected. Before, only frames that stopped arriving were noticed, so a frozen picture ran on stream for 5 hours.
  - When the picture is unchanged for `capture_freeze_seconds` (default `120`), ignoring the no-signal screen, the capture daemon restarts and resets the card.
  - The owner gets a DM when this happens, again after 3 failed resets, and on recovery. Repeated resets back off.
- OBS overlay synchronization now confirms measured delays during hunts. True matches against OBS's compressed video scored an error of 3–7, above the old limit of 6, and every ambiguous check cleared the confirmation streak. The overlays stayed on the 2.7 s fallback, about 0.9 s behind the 1.8 s video.
- Audio pops are smoothed over on Twitch and every other feed. About twice a second the Elgato 4K X's audio splices a USB packet early, then sends one garbage frame and three silent ones. The capture daemon bridges the dropout and fades out the splice, adding 1.3 ms of latency. Sharp discontinuities in a 30 s capture fell from 82 to 15.
- A refreshed Twitch token is saved as soon as Twitch issues it. Before, a failed validation or a stop in between left a spent refresh token, forcing `/twitch auth` again. Rejected refreshes are logged with Twitch's reason.
- A Twitch token that can't be renewed because `TWITCH_CLIENT_SECRET` is missing is kept, and the error says to set the secret. Before, both tokens were deleted every few hours.
- The scene matcher no longer crashes with `KeyError: None` when a macro clears its target scene during a check.

## 1.7.4

### Added
- Automatic OBS overlay synchronization: `OverlaySyncCog` checks displayed video age every five seconds against recent capture thumbnails while streaming or recording. Three consistent, unambiguous matches gradually adjust input and scene-score overlays, leaving video, macros, and WebRTC timing unchanged. Matching supports up to ten seconds of video age; static or repeating scenes do not steer the delay.
- `obs_auto_sync` (default `true`) enables automatic overlay synchronization. Disconnects, source restarts, or an unavailable synchronization cog restore the configured `obs_feed_delay_ms + obs_overlay_lag_ms` fallback. `/api/stream_stats` exposes the effective `obs_overlay_delay_ms`.

### Changed
- `bin/install.sh` refreshes installed package metadata without changing dependencies and verifies the installed version.
- Moved the OBS watermark to the bottom-right corner in the default layout and deployment examples.
- Automatic shiny clips now use the effective measured OBS overlay delay, when available, plus `twitch_clip_delay_seconds`.

### Fixed
- OBS and WebRTC feeds automatically recycle only the affected FFmpeg encoder after a 15-second startup grace period and two consecutive 15-second windows below half the available frame rate. Normal frame-rate reduction and missing capture do not trigger recovery; the bot and macros keep running.
- Encoder shutdown terminates FFmpeg before closing its pipes, preventing blocked raw-frame writes from hanging cleanup. Encoder recreation also resets the video timestamp gate.
- Blank game-title OCR no longer erases the last detected game or clears cyclient's Rich Presence. Until a title is known, active hunts use Nintendo Switch as the activity name.

## 1.7.3

### Added
- `/twitch start` and `/twitch stop` ask you to confirm with a button before anything happens, so they can't be triggered by accident. Only the person who ran the command can press it, and the buttons expire after a minute, leaving the stream as it was. The result replaces the prompt.
- `/twitch start` asks for Twitch approval first when it's needed (no token, a missing scope or a revoked token), then starts once you approve or after 5 minutes. When the token is fine it starts straight away.
- A possible shiny found while streaming is clipped on Twitch once the input visualizer's delay plus `twitch_clip_delay_seconds` (default `10`) has passed; the clip is titled after the hunt (e.g. "Shiny Cresselia!"), and the owner gets the clip's edit link. This adds the `clips:edit` scope, so run `/twitch auth` again.
- A stream that shows the capture card's no-signal screen for `twitch_no_signal_stop_minutes` (default `10`) is stopped, and the owner gets a DM.
- Streams restart automatically after `twitch_restart_hours` (default `24`), well before Twitch's 48-hour cutoff, and the owner gets a DM.
- A subtle `Cynthia (version)` watermark in the top-right corner of the OBS scene: a new `watermark` pane kind, included in the default and example layouts.
- `/api/streamelements/uptime`, `/api/streamelements/online` and `/api/streamelements/description` return plain text for StreamElements custom commands: the bot's uptime, and the hunt or custom status. `activity_stats.json` now also carries `hunt`, `self_encounter` and `status`.
- The bot can set the Twitch title and category from the detected game and hunt. Set `TWITCH_CLIENT_ID` (and `TWITCH_CLIENT_SECRET` for a confidential client), then run `/twitch auth`. A game or hunt must hold for `twitch_info_confirm_seconds` (default `60`). The channel is set once and changed again only for a different game or hunt, so edits made on Twitch stay. `twitch_categories` maps game titles that Twitch names differently; `twitch_auto_info: false` turns it off.

### Changed
- CV and NXBT worker loops now delegate scene analysis, preview publication, connection handling, restart timers, playback, and cleanup to named helpers without changing their ordering or thresholds.
- Completed missing production-code and script docstrings, clarified dense SSIM and frame-ownership logic, and refreshed the configuration and OBS deployment examples. All shipped macro definitions match the drive, with their conditional dependencies verified.
- More command replies are embeds. `/twitchurl` shows whether the channel is live, with the stream's title, category and viewers once the bot is authorized. `/obs show` shows the screenshot like `/show`, with the video mode and how long OBS has been streaming and recording. The others are `/twitch status`, the bandwidth-test report, the Twitch approval prompt, `/help`, `/get_macro`, `/loaded_modules` and `/loaded_commands`. Errors and one-line confirmations stay plain text. New embeds can use `cynthia.utils.embeds` for a consistent look.
- `/twitch url` is now `/twitchurl`, open to everyone in servers and DMs. It also says whether the channel is live: Twitch is asked once the bot is authorized, so bandwidth tests count as offline; otherwise it goes by OBS. The link is sent either way.
- OBS overlay text is about 3 px larger at 1080p (ssim 25 px, stats 28 px, chat 22.5 px, watermark 23.5 px). The default stats pane is taller (`h: 0.32`) to fit it.
- Updated the sample macros. `cresselia` drops the walk and A presses between its first `hold B V` and the menu. `encounter_roamer` closes the bag if it opened (new `try_close_bag` and `encounter_proceed` helpers, using the new `bdsp_bag` scene). `screen_record` waits 2 seconds after saving the clip.
- The default NXBT watchdog timeout is 10 minutes (was 15).

### Fixed
- Messages deleted on Twitch, and messages from users who are timed out or banned, now disappear from the chat pane; `/clear` empties it.
- The OBS overlay's inputs and scene-match panes now lag by `obs_feed_delay_ms`, so button presses line up with the delayed OBS video instead of showing about a second early. `/api/inputs` and `/api/ssim_data` take `feed=obs` with `delayed=true` for this. The OBS video also trails by encode, OBS buffering and decode time (measured at about 2.7 s in total), so the new `obs_overlay_lag_ms` setting (default `1700`) adds that on top. For quick tuning, `?lag=<ms>` on the inputs pane's browser source URL adds a further delay.

## 1.7.2

### Fixed
- All `discord.*` loggers now start at INFO, muting the DEBUG chatter from the gateway, HTTP, client and state loggers.
- Audio capture failures at startup (such as ALSA not finding the card yet) are logged quietly; a warning appears only after 3 consecutive failed attempts. A capture that drops out mid-stream still warns.
- Restarting no longer logs `BrokenPipeError` tracebacks from the OBS cog: its poll stops and its unload finishes quietly once the daemon manager has shut down.

## 1.7.1

### Fixed
- Silence routine `discord.gateway` events below WARNING while keeping warnings and errors visible.

## 1.7.0

### Added

#### Streaming and OBS
- `/twitch` (start, stop, test, url, uptime, status), `/obs` (framerate, resolution, record, stop, layout, show) and `/webstream` (framerate, resolution) commands, owner-only and DM-only, driving OBS through obs-websocket. New env keys `OBS_WS_*`, `OBS_STREAM_KEY`, `TWITCH_STREAM_KEY`, `TWITCH_CHANNEL`.
- OBS feed: while OBS is open, an NVENC H.264 stream is sent to `udp://127.0.0.1:5000`, with an importable scene collection in `deploy/obs/` and `obs_feed*` config keys. `obs_feed: always` sends it even when OBS is not open (`true` follows OBS, `false` disables).
- The OBS feed is held back one second by default (`obs_feed_delay_ms`) as a safety buffer. Audio rides in the same MPEG-TS, so it stays in sync.
- Customizable OBS scene from `obs_layout.yaml` (see `obs_layout.example.yaml`), with video, input, SSIM, hunt statistics and Twitch chat panes. The statistics pane is titled by the current activity and hidden without one; it shows encounters, hunt uptime, average per encounter, rate and time since the last encounter. Layouts refresh browser sources so edits apply without restarting OBS.
- `bin/obs.sh` runs OBS headless and `deploy/cynthia.sh` starts it in the tmux session. OBS renders on the GPU through a headless NVIDIA Xorg display (`deploy/xorg-headless.conf`), cutting its CPU use from about 440% to 120%, with Xvfb as the fallback.
- 60 fps: web and OBS frame rate and resolution are set independently (`web_fps`, `web_height`, `obs_fps`, `obs_height`) and change live. CV is always limited to 30 fps. The capture card switches mode to match the running endpoints.
- OBS outranks the web view: the WebRTC encoder and MediaMTX run at nice 15, and web viewers no longer raise the capture mode while OBS is streaming or recording.

#### Web viewer
- WebRTC: one NVENC H.264 + Opus encode is fanned out by a local MediaMTX (`cynthia/daemons/webrtc.py`, `/api/whep`), started only while a page wants it. Config keys `webrtc*`; set `webrtc_hosts` and forward UDP/TCP `webrtc_media_port` (8189) for viewers off the LAN.
- The page falls back to MJPEG plus MP3 audio when WebRTC cannot connect or `mediamtx` is missing, retries WebRTC every five minutes, and shows the active transport and playback stats (fps, dropped, freezes, loss, jitter). `transport=mjpeg` forces MJPEG for comparison.
- A wrench button opens a stats-for-nerds overlay (capture, encode and delivered fps, frame size, cache hit rate, dropped frames, stream delay, audio buffer and skips, CPU load averages), backed by `/api/stream_stats`.
- Audio: the web viewer plays the capture card's audio with a mute toggle and volume slider; sync is automatic via `/api/sync`.
- `stream_delay_ms` (default 1000) holds the web stream's video back so the audio buffer can ride out hiccups; CV and OBS never see this delay.
- Viewer counts include WebRTC viewers. The viewer keeps its size and shows an empty dark frame while the bot restarts or no feed is connected.
- The SSIM toggle is a brain icon and the stats wrench sits rightmost. The input visualizer has a smaller, redrawn controller pad (SL/SR rails hidden, triggers stacked at the edges, taller body).
- Behind a reverse proxy, allow `/api/sync`, `/api/stream_stats`, `/api/activity_stats`, `/api/webrtc` and `/api/whep`.

#### Capture, audio and CV
- At 1080p the capture card is read as raw NV12 and published to a second shared ring, so the OBS and web encoders feed NVENC without the CPU BGR conversion (about 2.8 ms per frame instead of 12.7 ms, and half the bytes through the pipe). CV and the web page still get BGR derived from the same frame, and the card falls back to YUYV if it gives no usable NV12.
- An `AudioDaemon` captures the Elgato's ALSA audio into a shared ring with live-edge catch-up. It idles when there is no web listener and the OBS feed is not running. The OBS feed muxes it as AAC on the same wall clock as the video.
- The MPEG-TS feed no longer packs about 180 ms of audio per packet (`-pes_payload_size 0`, zero mux delay), which made WebRTC audio arrive in bursts and pop. Audio capture errors and silent gaps are logged.
- CV scene matching is about 100x cheaper (about 210 ms to under 2 ms per frame): SSIM runs on OpenCV box filters with cached reference statistics (scores match skimage to 1e-6), the home, AFK home and no-signal scenes are re-scored every 1 s, 1 s and 10 s, and a thumbnail check skips hopeless comparisons.
- The OBS and WebRTC feeds copy each frame and free its ring slot before the pipe write, so slow encoders no longer make capture drop frames.
- Audio capture keeps the tail of a pipe read that ends mid-frame instead of dropping it, which shifted later audio by a sample and could click.

#### Logging
- Colorized, standardized logging through `cynthia.utils.log`: module and message stand out from the boilerplate, and PaddleOCR / OpenCV model-load chatter is silenced on startup.

### Changed
- Video pipeline: triple-buffered locked frame ring, threaded YUYV 30 fps capture, event-driven stream encoder with a frame-hash JPEG cache, and half-size scene comparison.
- PaddlePaddle is now chosen at install time with an extra: `pip install -e ".[dev,cpu]"` or `".[dev,gpu]"` (the GPU build needs Paddle's CUDA package index; see the README). Install exactly one. `paddlepaddle` is no longer a base dependency, so installs without either extra have no OCR backend.
- OCR runs on the GPU when Paddle was built with CUDA and falls back to the CPU otherwise.
- A failed first controller connection no longer sends the "Connection to NXBTDaemon lost!" alert; that is kept for dropped connections.
- Packaging includes the web pages and static files (`cynthia.site`), so non-editable installs serve the viewer.

### Fixed
- OCR now runs on the GPU inside the CV process: importing Paddle in the parent broke CUDA in every forked daemon, which crashed CV and stalled ternaries.
- Frames are no longer upside down; the vertical flip only applies to MJPG capture, not YUYV.
- OBS scene collection reads the UDP feed with a larger socket buffer, which removes dropped frames and audio gaps.
- `scrape_text` sliced columns twice and returned the wrong region.
- The web and OBS video feeds no longer slow to about one frame a second after running a while: a stalled audio pump or skipped ring audio left the audio behind real time, and ffmpeg held the video back to match. Lasting shortfalls are now padded with silence, and audio that runs slightly slow is stretched by up to 2% to stay level with real time, which removes the 60 to about 38 fps decay on the OBS feed.
- A short visit to the HOME screen no longer replaces the game in the status; HOME only shows after it has been up for more than 5 seconds.
- The web viewer's activity pane stayed hidden while playing, because playing statuses carry no name; the details line is now its title, as in the OBS overlay.

## 1.6.0

### Added
- Ternary macro steps: `scene ? true_macro : false_macro`.
- `/about` command with project version and startup details.
- Custom status, a scene setup tool (`tools/scene_setup.html`) and scene files.
- Quick settings guard during macros.
- Hunt watchdog (15-minute minimum timeout), improved statistics and an improved video feed page.
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
- Upgraded OCR to PaddleOCR 3.7 and PaddlePaddle 3.2.2 (`ocr.predict` API); first run downloads new models.
- Removed the unused `about-time` and `grapheme` dependencies.
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
