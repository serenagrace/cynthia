# LLM chat cog

**Source:** `cynthia/bot/cogs/llmchat.py` — `LLMChatCog`; model, memory, and
moderation work is delegated to `cynthia/llm/`.

## Responsibility and task model

`LLMChatCog` connects Twitch chat events to the configured model and optional
voice output. It uses a single bounded message queue (capacity 500) and one
worker to serialize replies and switching actions rather than allowing every
chat event to start a concurrent model request. The worker can handle
moderation, memory/journal updates, and optional responses according to the
active configuration and channel state.

The cog owns background event and memory loops (approximately two seconds and
60 seconds, respectively) and cancels them on unload. It tracks active chat,
voice, and switching state, and forwards owner-facing notices through the
existing bot services. The actual LLM client, prompting, storage, and voice
implementation are separate `cynthia/llm/` components.

## Extension and tests

Keep rate-sensitive chat work in the serialized worker and apply queue bounds
before adding new event sources. Do not call a model or synthesis provider
directly from a Discord listener. Keep user-facing safety, provider
configuration, and data retention documented in the
[local chat guide](../../local-chat.md). Add focused tests for queue ordering,
moderation, or provider-independent behavior in `tests/`; do not require live
Discord/Twitch credentials for ordinary unit tests.
