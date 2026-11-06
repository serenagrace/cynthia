"""Talk to a local Ollama server with settings from the bot config."""

import asyncio
import re

import aiohttp

DEFAULT_PROMPT = (
    "You are Cynthia, a cheerful, witty bot that streams Pokémon shiny hunts on "
    "Twitch. You chat like a friendly regular: casual, playful, a little teasing, "
    "never formal or robotic. Talk like you're hanging out in chat, not hosting "
    "a customer-service desk: contractions, quick reactions, dry jokes, no stock "
    "greetings or polished sign-offs. Don't open every reply with the viewer's "
    "name; usually just answer. Keep replies to one or two short sentences. Use "
    "lowercase when it feels natural and an emote only now and then. Never say you "
    "are an AI assistant, never use lists or markdown, and don't make up facts "
    "about the hunt that aren't in your notes."
)

# Twitch rejects chat messages longer than this
MAX_REPLY_CHARS = 500
# A speaker label the model copied from the transcript, like `Cynthia (you):`
SPEAKER = re.compile(
    r"^\s*(?:cynthia|assistant|[A-Za-z0-9_]{3,25}\s*\((?:streamer|you)[^)]*\))"
    r"(?:\s*\([^)]*\))?\s*:\s*",
    re.I,
)


class LLMError(Exception):
    """Raised when the model server can't produce a reply."""


def setting(config, key, default):
    """Read one setting from the config mapping, falling back to `default`."""
    value = config.get(key, None)
    return default if value is None or value == "" else value


def flag(config, key, default=False):
    """Read a boolean setting, accepting strings set with `/cset`."""
    value = setting(config, key, default)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def clean_reply(text):
    """Strip a self-added speaker label and trim to Twitch's message limit."""
    text = SPEAKER.sub("", text.strip()).strip().strip('"').strip()
    text = " ".join(text.split())
    if len(text) <= MAX_REPLY_CHARS:
        return text
    cut = text[:MAX_REPLY_CHARS]
    end = max(cut.rfind(mark) for mark in ".!?")
    return cut[: end + 1] if end > MAX_REPLY_CHARS // 2 else cut.rstrip() + "…"


class LLMClient:
    """Send chat requests to Ollama one at a time."""

    def __init__(self, config):
        """Use `config` for the server, model, persona and generation settings."""
        self.config = config
        self.lock = asyncio.Lock()

    @property
    def url(self):
        """Base URL of the Ollama server."""
        return str(setting(self.config, "llm_url", "http://127.0.0.1:11434"))

    @property
    def model(self):
        """Name of the Ollama model used for replies."""
        return str(setting(self.config, "llm_model", "llama3.2:3b"))

    @property
    def prompt(self):
        """System prompt describing the persona."""
        return str(setting(self.config, "llm_system_prompt", "")).strip() or (
            DEFAULT_PROMPT
        )

    @property
    def notes(self):
        """Extra notes the owner keeps about the stream and channel."""
        return str(setting(self.config, "llm_context", "")).strip()

    def options(self, max_tokens=None, temperature=None):
        """Generation settings that keep the model fully on the GPU."""
        return {
            "num_ctx": int(setting(self.config, "llm_num_ctx", 4096)),
            "num_gpu": 99,
            "num_predict": int(
                max_tokens or setting(self.config, "llm_max_tokens", 80)
            ),
            "temperature": float(
                setting(self.config, "llm_temperature", 0.85)
                if temperature is None
                else temperature
            ),
            "repeat_penalty": 1.1,
        }

    async def request(self, path, payload=None, timeout=120):
        """Call the Ollama API and return its JSON response."""
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        try:
            async with aiohttp.ClientSession(timeout=client_timeout) as session:
                method = session.post if payload is not None else session.get
                async with method(self.url + path, json=payload) as response:
                    data = await response.json(content_type=None)
                    if response.status >= 400:
                        raise LLMError(data.get("error", f"HTTP {response.status}"))
                    return data
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise LLMError(f"Couldn't reach Ollama at {self.url}: {e}") from e

    async def chat(
        self, messages, *, max_tokens=None, temperature=None, json_format=False
    ):
        """Generate one reply to `messages`; returns `(text, metadata)`.

        Requests run one at a time so bursts can't stack up GPU work.
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": self.options(max_tokens, temperature),
        }
        if json_format:
            payload["format"] = "json"
        async with self.lock:
            data = await self.request("/api/chat", payload)
        return data.get("message", {}).get("content", "").strip(), data

    async def loaded(self):
        """Return Ollama's entry for the loaded model, or None if it isn't loaded."""
        data = await self.request("/api/ps", timeout=10)
        for entry in data.get("models", []):
            if entry.get("name") == self.model or entry.get("model") == self.model:
                return entry
        return None
