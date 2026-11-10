# Local chat model and voice

Cynthia can read Twitch chat and generate replies through a local model served
by [Ollama](https://ollama.com). This integration is optional. It is not a
hosted model API: model inference and configuration use the configured Ollama
server (`llm_url`, default `http://127.0.0.1:11434`).

## Install Ollama

Install Ollama using its official installation instructions and fetch the
default model:

```bash
ollama pull llama3.2:3b
```

The 3B model with a 4096-token context uses about 2.5 GB of VRAM. To constrain
Ollama to one loaded model and one concurrent request, an optional systemd
override is:

```ini
[Service]
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_KEEP_ALIVE=30m"
```

The voice integration uses Piper TTS and an OBS source named `Cynthia Voice`.
Piper inference runs on CPU. The voice is included in OBS output, not the
WebRTC browser viewer.

## Twitch authorization

Set `TWITCH_CHANNEL` and authorize the broadcaster with `/twitch auth` to
enable Twitch API features. The model's chat listener uses the channel and a
valid Twitch authorization. To post replies under a separate Twitch bot
account:

1. Create the bot account and run owner-only `/twitch botauth`.
2. Open the approval link in a private browser window signed in as that bot
   account.
3. Keep `twitch_chat_token.json` private in the bot working directory.

When authorized, the bot account is used for chat; replies still appear in the
configured channel. If its token is invalid or expires, the bot reports a
posting error rather than falling back to the broadcaster account.

## Controls

All `/llm` controls are owner-oriented; use them in the owner's DMs.

| Command | Purpose |
| --- | --- |
| `/llm switch [name] [enabled]` | Inspect or toggle `listen`, `learn`, `speak`, `events`, `voice`, `talk`, or all switches. |
| `/llm say`, `/event`, `/trigger`, `/moderate` | Test reply generation, an event, reply eligibility, or filtering. |
| `/llm state`, `/chat`, `/log`, `/filtered` | Inspect model state, recent chat, decisions, or filtered drafts. |
| `/llm prompt [default]`, `/context`, `/show`, `/sysprompt` | Edit or inspect persona and context. |
| `/llm memory`, `/memories`, `/learn` | View/edit chatter memory and apply a memory update. |
| `/llm teach`, `/lessons`, `/unlearn` | Manage lessons. |
| `/llm tts`, `/voices`, `/setvoice` | Test speech and inspect/select Piper voices. |
| `/llm reset`, `/status` | Clear the test conversation or inspect Ollama/GPU state. |

The master `llm_enabled` switch disables all behavior. `listen` and `learn`
default on; `speak`, spontaneous `events`, `voice`, and owner free-form `talk`
default off. Prompt/context edits made with commands are saved to
`config.yaml` at shutdown.

## Reply behavior and safety

Mentions and recent follow-up questions receive a reply attempt; other
questions, short messages, and ordinary chat use configured probabilities.
Cooldowns, per-chatter throttles, repetition checks, and hard post-rate caps
limit output. Parenthesized text is removed before model input, which can be
used to talk without the bot hearing the parenthetical portion. Event remarks
are independent of normal replies and are off by default.

Generated replies pass safety and repetition filters and are bounded to
Twitch's 500-character limit. When a draft fails, it can be regenerated up to
three times. The owner can be notified of blocked replies and review recent
filters in `/llm filtered`. No model output should be treated as guaranteed
safe; leave public speaking disabled until its prompt and behavior have been
tested in a private setting.

The streamer is treated as trusted input. Chatter memories are based on
first-person statements; claims about other people are treated as unconfirmed.
The bot uses stated pronouns or sufficiently repeated evidence, and learns
nicknames after multiple uses. Review memory before relying on it; use
`/llm memory` to inspect and edit notes.

## Memory and journal

When `learn` is enabled, chatter notes are updated in batches or after a period
of inactivity. Recent messages, notes, and lessons can be included in model
context. Chat journaling is written to
`chat_journal/YYYY-MM-DD.jsonl` on the drive and records messages, decisions,
prompts, drafts, and replies. Journals can contain personal information and
should be stored and retained accordingly. Disable learning or protect the
drive if this data is not desired.

## Configuration reference

See `config.example.yaml` for the defaults. The most useful groups are:

| Settings | Purpose |
| --- | --- |
| `llm_url`, `llm_model`, `llm_num_ctx` | Ollama location, model, and context size. Larger contexts use more memory. |
| `llm_enabled`, `llm_listen`, `llm_learn`, `llm_speak`, `llm_events`, `llm_voice`, `llm_owner_talk` | Master and behavior switches. |
| `llm_system_prompt`, `llm_context` | Persona and extra notes. |
| `llm_reply_*_chance`, `llm_followup_seconds`, `llm_streamer_*` | Reply eligibility and streamer-specific behavior. |
| `llm_reply_*_seconds`, `llm_user_cooldown_seconds`, `llm_mention_cooldown_seconds` | Overall and per-user pacing. |
| `llm_max_posts_per_minute`, `llm_max_posts_per_10_minutes` | Hard chat rate caps; `0` disables the respective cap. |
| `llm_event_*`, `llm_idle_minutes` | Event and idle remarks. |
| `llm_allowed_words`, `llm_blocked_words`, `llm_notify_filtered` | Filter exceptions/additions and owner notifications. |
| `llm_memory_*`, `llm_*_history` | Memory update cadence and context history. |
| `llm_max_tokens`, `llm_temperature` | Reply length and sampling behavior. |
| `tts_voice`, `tts_loudness`, `tts_speed` | Piper voice and output level. |

The default `llm_model` is `llama3.2:3b`; the default context size is 4096
tokens, temperature 0.85, and maximum reply length 80 tokens. Tune settings
gradually and monitor `/llm log`, `/llm state`, and owner alerts.
