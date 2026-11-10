"""Default environment, bot configuration, context, and permission values."""


class Defaults:
    """Container for default configuration and permission mappings."""

    env = {
        "DISCORD_BOT_TOKEN": None,
        "OTP_SECRET": None,
        "DRIVE_PATH": None,
        "ELGATO_USB_ID": None,
        "SYNC_GUILD_ID": None,
        "STATUS_HOSTS": None,
        "CYNX_PASSPHRASE": None,
        "YTDL_COOKIES_FILE": None,
        # obs-websocket (OBS 28+): Tools > WebSocket Server Settings
        "OBS_WS_HOST": None,
        "OBS_WS_PORT": None,
        "OBS_WS_PASSWORD": None,
        # Stream key OBS uses; TWITCH_STREAM_KEY takes precedence for /twitch
        "OBS_STREAM_KEY": None,
        "TWITCH_STREAM_KEY": None,
        # Channel name for /twitchurl and the chat overlay
        "TWITCH_CHANNEL": None,
        # Twitch app credentials (dev.twitch.tv) for setting the title and category
        "TWITCH_CLIENT_ID": None,
        "TWITCH_CLIENT_SECRET": None,
    }
    config = {
        "silent": False,
        "debug": False,
        "owner": None,
        # restart the looping macro 5s after an encounter
        "encounter_reset": True,
        # CyNX discovery shares the command port number over UDP.
        "cynx_enabled": True,
        "cynx_auto_connect": True,
        "cynx_command_port": 3140,
        "cynx_macro_port": 3141,
        "cynx_discovery_timeout": 1.0,
        "cynx_discovery_interval": 2.0,
        "cynx_heartbeat_interval": 1.0,
        # systemd units checked by the /status command
        "status_services": ["cynthia.service"],
        # send the video feed to OBS (over UDP) while OBS is running
        # True follows OBS, "always" feeds regardless, False disables
        "obs_feed": True,
        "obs_feed_port": 5000,
        "obs_feed_bitrate": "50M",
        # frame rate (15, 24, 30, 60) and height (480, 720, 1080) of each endpoint;
        # change them live with /webstream and /obs. CV is always capped at 30 fps.
        "web_fps": 30,
        "web_height": 720,
        "obs_fps": 60,
        "obs_height": 1080,
        # OBS scene the bot manages, and the YAML file describing its panes
        "obs_scene": "Cynthia",
        "obs_layout_file": "obs_layout.yaml",
        # Twitch video bitrate (kbps) applied to OBS when streaming from Discord
        "twitch_bitrate_kbps": 6000,
        # restart a stream this long (hours) before Twitch ends it at 48; 0 disables
        "twitch_restart_hours": 24,
        # fixed chat message (not the model) on /restart and /reboot while live; "" disables
        "twitch_reboot_message": "be right back, rebooting real quick!",
        # fixed chat message on /shutdown, posted before the stream is ended; "" disables
        "twitch_goodbye_message": "that's all for now, thanks for hanging out! bye!",
        # stop a stream that shows the capture card's no-signal screen this long; 0 disables
        "twitch_no_signal_stop_minutes": 10,
        # reset the capture card when its picture hasn't changed this long (seconds)
        # while frames keep arriving, and DM the owner; 0 disables
        "capture_freeze_seconds": 120,
        # clip the stream when a shiny is found (needs /twitch auth)
        "twitch_auto_clip": True,
        # seconds after the shiny reaches the input visualizer (OBS delay) to clip
        "twitch_clip_delay_seconds": 10,
        # set the Twitch title/category from the detected game and hunt
        "twitch_auto_info": True,
        # how long a new game or hunt must hold before the channel is changed
        "twitch_info_confirm_seconds": 60,
        # detected game title -> Twitch category name or id, when they differ
        "twitch_categories": {},
        # DM viewer chat to the owner, regardless of stream or local model state
        "twitch_forward_chat": True,
        # serve the web viewer over WebRTC (needs the `mediamtx` binary); the page
        # falls back to MJPEG. Media flows over UDP and TCP `webrtc_media_port`;
        # list public IPs or hostnames in `webrtc_hosts` for viewers off the LAN
        "webrtc": True,
        "webrtc_port": 8889,
        "webrtc_media_port": 8189,
        "webrtc_api_port": 9997,
        "webrtc_ingest_port": 5100,
        "webrtc_bitrate": "8M",
        "webrtc_hosts": [],
        # hold the OBS feed back this long (0 = send immediately)
        "obs_feed_delay_ms": 1000,
        # extra lag for OBS overlay inputs/SSIM, covering encode, OBS buffer and decode
        "obs_overlay_lag_ms": 1700,
        # measure OBS video age and adjust overlay timing when matches are unambiguous
        "obs_auto_sync": True,
        # hold the web stream's video back this long so audio can buffer smoothly
        "stream_delay_ms": 1000,
        # local chat model served by Ollama, tried out with the owner-only /llm commands
        "llm_url": "http://127.0.0.1:11434",
        "llm_model": "llama3.2:3b",
        # persona for the model; empty uses the built-in one (edit with /llm prompt)
        "llm_system_prompt": "",
        # notes added under the persona (edit with /llm context)
        "llm_context": "",
        "llm_max_tokens": 80,
        "llm_temperature": 0.85,
        # context window in tokens; room for state, memories and lessons
        # (about 2.5 GB of VRAM with the 3B model)
        "llm_num_ctx": 4096,
        # owner teaching: most lessons kept, and conversation turns remembered
        "llm_lessons_max": 40,
        "llm_owner_history": 12,
        # plain owner DMs (not commands) go to the model as a conversation
        "llm_owner_talk": False,
        # switches, also set with /llm switch; llm_enabled off turns them all off
        "llm_enabled": True,
        "llm_listen": True,
        "llm_learn": True,
        "llm_speak": False,
        "llm_events": False,
        "llm_voice": False,
        # also talk while the stream is offline
        "llm_speak_offline": False,
        # context for each reply: recent chat lines, the chatter's earlier lines
        # this stream, memories of chatters they name, and other names in chat
        "llm_context_messages": 8,
        "llm_user_history": 8,
        "llm_mentioned_memories": 3,
        "llm_present_names": 10,
        # Pokémon facts (legendaries, types, regions, games) looked up from
        # the game, hunt target and recent chat, beyond the one-line overview
        "llm_pokedex_facts": 6,
        # chat names that mean the bot, and chatters never read or answered
        "llm_bot_names": ["cynthia"],
        "llm_ignored_chatters": ["streamelements", "nightbot", "streamlabs", "moobot"],
        # words the chat filter lets through or adds
        "llm_allowed_words": [],
        "llm_blocked_words": [],
        # chance to answer each kind of chat message
        "llm_reply_mention_chance": 1.0,
        "llm_reply_question_chance": 0.5,
        "llm_reply_short_chance": 0.03,
        "llm_reply_random_chance": 0.05,
        # seconds between any two replies, between replies to messages that
        # don't name the bot, and between replies to the same chatter (shorter
        # when they name the bot)
        "llm_reply_min_seconds": 9,
        # the overall cooldown varies on a bell curve with this spread (most
        # pauses fall within mean ± 2x this)
        "llm_reply_jitter_seconds": 2.5,
        "llm_reply_cooldown_seconds": 30,
        "llm_mention_cooldown_seconds": 5,
        # each mention in the last llm_mention_window_seconds, past the first
        # llm_mention_spam_free, multiplies the chance of answering the next
        # one by llm_mention_spam_factor
        "llm_mention_window_seconds": 60,
        "llm_mention_spam_free": 2,
        "llm_mention_spam_factor": 0.5,
        "llm_user_cooldown_seconds": 20,
        # hard caps on her posts, whoever she answers (shiny news exempt); 0 = off
        "llm_max_posts_per_minute": 4,
        "llm_max_posts_per_10_minutes": 20,
        # a question from someone the bot answered within this many seconds is
        # treated as addressed to it, with llm_reply_followup_chance
        "llm_followup_seconds": 90,
        "llm_reply_followup_chance": 1.0,
        # reply chances rise towards certain the quieter chat is (fully with one
        # chatter in llm_quiet_window_seconds, not at all with llm_busy_chatters)
        # and the longer the bot has been silent (fully after
        # llm_silence_boost_seconds); short messages get none; 0 turns either off
        "llm_quiet_window_seconds": 180,
        "llm_busy_chatters": 5,
        "llm_silence_boost_seconds": 900,
        # extra lift for the streamer's own messages that aren't aimed at
        # someone else (no @name, reply or "name:" to another chatter), and the
        # chance of answering the streamer's questions that aren't
        "llm_streamer_boost": 0.15,
        "llm_streamer_question_chance": 1.0,
        # chance to remark on stream events, with a cooldown between remarks
        "llm_event_shiny_chance": 1.0,
        "llm_event_watchdog_chance": 0.75,
        "llm_event_failsafe_chance": 0.5,
        "llm_event_encounter_chance": 0.05,
        "llm_event_idle_chance": 1.0,
        "llm_event_cooldown_seconds": 60,
        # minutes without chat or remarks before an idle remark
        "llm_idle_minutes": 20,
        # repetition: how alike (0-1) two messages must be to count as a repeat,
        # the reply chance kept per repeat of recent chat, and the chance a reply
        # close to something said lately still goes out (per repeat)
        "llm_repeat_similarity": 0.8,
        "llm_repeat_input_factor": 0.3,
        "llm_repeat_allow_chance": 0.2,
        # DM the owner about replies the filters block (repeats only if enabled),
        # at most once per llm_notify_seconds; blocks from the last
        # llm_mistake_hours are listed in the prompt as mistakes to avoid
        "llm_notify_filtered": True,
        "llm_notify_repetition": False,
        "llm_notify_seconds": 60,
        "llm_mistake_hours": 24,
        # chatter memory: update after this many new messages, or once they go quiet
        "llm_memory_batch": 6,
        "llm_memory_idle_minutes": 15,
        "llm_memory_max_chars": 500,
        # macros a ternary branches to when the hunt macro gets lost
        "failsafe_macros": ["screen_record"],
        # Piper text-to-speech voice (see /llm voices); runs on the CPU
        "tts_voice": "en_US-amy-medium",
        "tts_speaker": None,
        "tts_speed": 1.0,
        # speech level in dBFS (OBS meter) every voice is normalized to; the
        # game feed averages about -29, so -20 sits clearly but not loudly on top
        "tts_loudness": -20,
        # extra OBS volume on the voice source; leave at 1.0 and tune tts_loudness
        "tts_stream_volume": 1.0,
    }
    context = {}
    perms = {
        "privileged": [],
        "nxbt": [],
        "drive": [],
        "owners": [],
        "admins": [],
        "allowed_commands": [],
    }
