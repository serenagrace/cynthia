"""Minimal Twitch Helix client for updating the channel's title and category."""

import asyncio
import json
import logging
import os
import time

import aiohttp

logger = logging.getLogger(__name__)

AUTH_URL = "https://id.twitch.tv/oauth2"
HELIX_URL = "https://api.twitch.tv/helix"
SCOPES = "channel:manage:broadcast clips:edit"
TOKEN_FILE = "twitch_token.json"
# Refresh this long before the access token expires
REFRESH_MARGIN_S = 300
# Twitch rejects longer stream titles
MAX_TITLE = 140
TIMEOUT = aiohttp.ClientTimeout(total=15)


class TwitchAPIError(Exception):
    """A Twitch API request failed."""


class TwitchAuthError(TwitchAPIError):
    """The bot has no usable Twitch authorization; run `/twitch auth`."""


class TwitchAPI:
    """Hold the channel's user token and make the few Helix calls the bot needs."""

    def __init__(self, client_id, client_secret, drive):
        """Use the app's credentials and keep tokens in the drive's token file."""
        self.client_id = client_id
        self.client_secret = client_secret or None
        self.drive = drive
        self.tokens = self._load()
        self._lock = asyncio.Lock()

    @classmethod
    def from_env(cls, env, drive):
        """Build a client from `.env`, or return None without `TWITCH_CLIENT_ID`."""
        client_id = env.get("TWITCH_CLIENT_ID", None)
        if not client_id:
            return None
        return cls(client_id, env.get("TWITCH_CLIENT_SECRET", None), drive)

    @property
    def authorized(self):
        """Whether a refresh token is stored."""
        return bool(self.tokens.get("refresh_token"))

    @property
    def login(self):
        """The authorized channel's login name, if known."""
        return self.tokens.get("login")

    def _load(self):
        """Read stored tokens, or start empty."""
        if not self.drive.exists(TOKEN_FILE, is_file=True):
            return {}
        try:
            with self.drive.open(TOKEN_FILE, "r") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Couldn't read the stored Twitch token: %s", e)
            return {}

    def _save(self):
        """Write the tokens, readable only by the bot's user."""
        path = self.drive.path(TOKEN_FILE)
        if path is None:
            return
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(self.tokens, f)

    def _client_form(self, **fields):
        """Form fields for the token endpoint, with the secret when there is one."""
        form = {"client_id": self.client_id, **fields}
        if self.client_secret:
            form["client_secret"] = self.client_secret
        return form

    async def start_device_flow(self):
        """Ask Twitch for a device code the owner approves at twitch.tv/activate."""
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                f"{AUTH_URL}/device",
                data={"client_id": self.client_id, "scopes": SCOPES},
            ) as response:
                body = await response.json(content_type=None)
        if "device_code" not in body:
            raise TwitchAPIError(f"Twitch refused the device code: {body}")
        return body

    async def finish_device_flow(self, flow):
        """Wait until the owner approves the device code, then store the tokens."""
        deadline = time.monotonic() + int(flow.get("expires_in", 1800))
        interval = max(1, int(flow.get("interval", 5)))
        form = self._client_form(
            scopes=SCOPES,
            device_code=flow["device_code"],
            grant_type="urn:ietf:params:oauth:grant-type:device_code",
        )
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            while time.monotonic() < deadline:
                await asyncio.sleep(interval)
                async with session.post(f"{AUTH_URL}/token", data=form) as response:
                    body = await response.json(content_type=None)
                if "access_token" in body:
                    await self._store(session, body)
                    return self.login
                if body.get("message") != "authorization_pending":
                    raise TwitchAPIError(f"Twitch authorization failed: {body}")
        raise TwitchAPIError("The Twitch authorization code expired.")

    async def _store(self, session, body):
        """Keep a new token pair and look up whose channel it belongs to."""
        async with session.get(
            f"{AUTH_URL}/validate",
            headers={"Authorization": f"OAuth {body['access_token']}"},
        ) as response:
            info = await response.json(content_type=None)
        if "user_id" not in info:
            raise TwitchAPIError(f"Twitch didn't accept the new token: {info}")
        self.tokens = {
            "access_token": body["access_token"],
            # Refresh tokens can be single-use, so always keep the newest one
            "refresh_token": body.get("refresh_token")
            or self.tokens.get("refresh_token"),
            "expires_at": time.time() + int(body.get("expires_in", 0)),
            "user_id": info["user_id"],
            "login": info.get("login"),
            "scopes": info.get("scopes", []),
        }
        self._save()

    async def _access_token(self, session, force=False):
        """Return a valid access token, refreshing it when it is close to expiry."""
        async with self._lock:
            if not self.authorized:
                raise TwitchAuthError("Twitch isn't authorized; run `/twitch auth`.")
            if not force and self.tokens.get("expires_at", 0) - REFRESH_MARGIN_S > (
                time.time()
            ):
                return self.tokens["access_token"]
            async with session.post(
                f"{AUTH_URL}/token",
                data=self._client_form(
                    grant_type="refresh_token",
                    refresh_token=self.tokens["refresh_token"],
                ),
            ) as response:
                body = await response.json(content_type=None)
            if "access_token" not in body:
                if response.status in (400, 401):
                    self.tokens = {}
                    self._save()
                    raise TwitchAuthError(
                        "Twitch authorization expired; run `/twitch auth` again."
                    )
                raise TwitchAPIError(f"Couldn't refresh the Twitch token: {body}")
            await self._store(session, body)
            return self.tokens["access_token"]

    async def _helix(self, method, path, **kwargs):
        """Make one Helix request, retrying once with a fresh token on a 401."""
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            for force in (False, True):
                token = await self._access_token(session, force)
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Client-Id": self.client_id,
                }
                async with session.request(
                    method, f"{HELIX_URL}/{path}", headers=headers, **kwargs
                ) as response:
                    if response.status == 401 and not force:
                        continue
                    text = await response.text()
                    if response.status >= 400:
                        raise TwitchAPIError(
                            f"Twitch {method} {path} failed ({response.status}): {text}"
                        )
                    return json.loads(text) if text else {}

    async def needs_authorization(self):
        """Whether `/twitch auth` is needed: no token, a missing scope, or a dead token.

        Network trouble doesn't count; the token may still be fine.
        """
        if not self.authorized:
            return True
        if any(not self.has_scope(scope) for scope in SCOPES.split()):
            return True
        try:
            async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
                await self._access_token(session)
        except TwitchAuthError:
            return True
        except (TwitchAPIError, aiohttp.ClientError, asyncio.TimeoutError):
            return False
        return False

    def has_scope(self, scope):
        """Whether the stored authorization grants `scope`."""
        return scope in self.tokens.get("scopes", [])

    async def create_clip(self, title=None, duration=None):
        """Clip the live stream; returns `{"id", "edit_url"}`.

        Twitch keeps the 90 seconds up to the call and publishes the last
        `duration` seconds (30 by default) of them.
        """
        if self.authorized and not self.has_scope("clips:edit"):
            raise TwitchAuthError(
                "Clipping needs a new Twitch authorization; run `/twitch auth` again."
            )
        params = {"broadcaster_id": self.tokens.get("user_id", "")}
        if title:
            params["title"] = title[:MAX_TITLE]
        if duration:
            params["duration"] = f"{min(max(float(duration), 5), 60):.1f}"
        body = await self._helix("POST", "clips", params=params)
        return body["data"][0]

    async def live_stream(self, login):
        """`login`'s live stream (title, game_name, viewer_count…), else None.

        Bandwidth tests aren't listed as live.
        """
        body = await self._helix("GET", "streams", params={"user_login": login})
        return next((s for s in body.get("data", []) if s.get("type") == "live"), None)

    async def find_category(self, name):
        """Return the id of the category named exactly `name`, or None."""
        body = await self._helix("GET", "games", params={"name": name})
        matches = body.get("data", [])
        return matches[0]["id"] if len(matches) == 1 else None

    async def update_channel(self, game_id=None, title=None):
        """Set the channel's category and/or title; omitted values stay as they are."""
        payload = {}
        if game_id:
            payload["game_id"] = game_id
        if title:
            payload["title"] = title[:MAX_TITLE]
        if not payload:
            return
        await self._helix(
            "PATCH",
            "channels",
            params={"broadcaster_id": self.tokens["user_id"]},
            json=payload,
        )
