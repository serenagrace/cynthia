"""YouTube lookup and per-server playback queues for Discord voice calls."""

import asyncio
import json
import logging
import math
import re
import urllib.parse
from collections import deque
from dataclasses import dataclass

import discord
import yt_dlp
from discord import app_commands
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

MAX_QUEUE = 100
MAX_PINS = 50
SEARCH_RESULTS = 8
# YouTube Music's top results are what it classes as songs; only the first few count
MUSIC_RESULTS = 10
# Each earlier search result gets a small edge so YouTube's own ranking breaks ties
RANK_PENALTY = 2
MUSIC_BONUS = 20
MUSIC_RANK_BONUS = 3
TOPIC_BONUS = 10
VERIFIED_BONUS = 3
OFFICIAL_BONUS = 4
# 2.5 points per power of ten in views, so a billion views is worth about 22
VIEWS_WEIGHT = 2.5
VIEWS_CAP = 22
OFF_VERSION_PENALTY = 25
REQUESTED_VERSION_BONUS = 15
# Most songs run 2 to 7 minutes; clips, long edits and mixes are rarely the request
SONG_SECONDS = (120, 7 * 60)
ACCEPTABLE_SECONDS = (60, 10 * 60)
MIX_SECONDS = 15 * 60
LENGTH_BONUS = 8
LENGTH_PENALTY = 20
MIX_PENALTY = 35
ARTIST_TITLE_BONUS = 6
ARTIST_CHANNEL_BONUS = 6
VEVO_BONUS = 4
# Pinned songs win when the query is at least this similar to the pin
PIN_MATCH_SCORE = 88
# Versions people rarely want unless they say so in the query
OFF_VERSION_WORDS = (
    "cover",
    "remix",
    "live",
    "karaoke",
    "instrumental",
    "reaction",
    "slowed",
    "reverb",
    "sped",
    "nightcore",
    "8d",
    "loop",
    "hour",
    "hours",
    "mashup",
    "acoustic",
    "parody",
    "tutorial",
    "lesson",
)
URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}
YDL_OPTIONS = {
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "format": "bestaudio/best",
    "skip_download": True,
    "socket_timeout": 15,
}


# Set from YTDL_COOKIES_FILE at startup; lets yt-dlp act as a logged-in session
cookie_file: str | None = None
MAX_PLAYLIST = 50
UNAVAILABLE_TITLES = ("[private video]", "[deleted video]")


class MusicError(app_commands.CheckFailure):
    """A user-facing failure; the command tree shows its message to the user."""


@dataclass
class Track:
    """One queued song."""

    title: str
    # Watch-page URL; the short-lived stream URL is resolved when playback starts
    url: str
    duration: int | None
    requester: str
    pinned: bool = False


@dataclass
class Pin:
    """A link a server wants returned for searches that resemble it."""

    title: str
    url: str
    duration: int | None
    # What people type to find it; defaults to the title
    query: str
    pinned_by: str

    def match_score(self, query: str) -> float:
        """Return how closely a search query resembles this pin."""
        query = query.lower().strip()
        # The alias is deliberate, so it may match loosely; the title must be near-exact
        return max(
            fuzz.WRatio(query, self.query.lower()),
            fuzz.token_sort_ratio(clean_title(query), clean_title(self.title)),
        )


class PinStore:
    """Per-server pinned songs, saved to the drive when one is available."""

    FILE = "music_pins.json"

    def __init__(self, drive=None):
        """Load saved pins; without a drive they last until the bot restarts."""
        self.drive = drive if drive is not None and drive.enabled else None
        self.pins: dict[str, list[Pin]] = {}
        if self.drive is None:
            return
        try:
            with self.drive.open(self.FILE, "r", touch=True) as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError):
            raw = {}
        for guild_id, pins in (raw if isinstance(raw, dict) else {}).items():
            self.pins[str(guild_id)] = [Pin(**pin) for pin in pins]

    def _save(self) -> None:
        """Write pins atomically so a crash can't truncate the file."""
        if self.drive is None:
            return
        path = self.drive.path(self.FILE)
        temp = path.with_suffix(".tmp")
        data = {guild: [vars(pin) for pin in pins] for guild, pins in self.pins.items()}
        temp.write_text(json.dumps(data, indent=2))
        temp.replace(path)

    def list(self, guild_id: int) -> list[Pin]:
        """Return a server's pins, oldest first."""
        return list(self.pins.get(str(guild_id), []))

    def add(self, guild_id: int, pin: Pin) -> bool:
        """Pin a song, replacing a pin with the same link; return whether it replaced one."""
        pins = self.pins.setdefault(str(guild_id), [])
        replaced = any(p.url == pin.url for p in pins)
        if not replaced and len(pins) >= MAX_PINS:
            raise MusicError(f"This server already has {MAX_PINS} pins.")
        pins[:] = [p for p in pins if p.url != pin.url]
        pins.append(pin)
        self._save()
        return replaced

    def remove(self, guild_id: int, index: int) -> Pin | None:
        """Remove the pin at a 1-based position and return it, if it exists."""
        pins = self.pins.get(str(guild_id), [])
        if not 1 <= index <= len(pins):
            return None
        pin = pins.pop(index - 1)
        self._save()
        return pin

    def match(self, guild_id: int, query: str) -> Pin | None:
        """Return the pin closest to a search query, if any is close enough."""
        best, best_score = None, PIN_MATCH_SCORE - 1
        for pin in self.pins.get(str(guild_id), []):
            if off_version_words(query, pin.title + " " + pin.query):
                # The query asks for a version (cover, live...) this pin isn't
                continue
            score = pin.match_score(query)
            # Later pins win ties, so re-pinning overrides an older choice
            if score >= best_score:
                best, best_score = pin, score
        return best


def is_url(query: str) -> bool:
    """Return whether the whole query is an HTTP(S) link."""
    return URL_PATTERN.fullmatch(query.strip()) is not None


def format_duration(seconds) -> str:
    """Format seconds as M:SS or H:MM:SS; unknown durations show as '?'."""
    if not seconds:
        return "?"
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _is_live(entry: dict) -> bool:
    """Return whether an entry is a live or upcoming stream, which can't be queued."""
    return bool(entry.get("is_live")) or entry.get("live_status") in (
        "is_live",
        "is_upcoming",
    )


def clean_title(title: str) -> str:
    """Drop bracketed tags and featuring credits so titles compare on artist and song."""
    title = re.sub(r"[(\[{][^)\]}]*[)\]}]", " ", title.lower())
    title = re.sub(r"\b(ft|feat|featuring)\b\.?.*$", " ", title)
    return re.sub(r"[^\w\s]|_", " ", title).strip()


def off_version_words(title: str, query: str) -> set[str]:
    """Return alternate-version words the title has but the query didn't ask for."""
    title, query = title.lower(), query.lower()
    return {
        word
        for word in OFF_VERSION_WORDS
        if re.search(rf"\b{word}\b", title) and not re.search(rf"\b{word}\b", query)
    }


def _video_id(url: str | None) -> str | None:
    """Return the video ID from a YouTube or YouTube Music watch URL."""
    match = re.search(r"[?&]v=([\w-]{11})", url or "")
    return match.group(1) if match else None


def score_entry(
    query: str, entry: dict, rank: int, music_ids: dict[str, int] | None = None
) -> float:
    """Score how well a search result fits a song request.

    Text similarity leads; YouTube Music membership, official-looking uploads and
    view counts lift the original recording over covers and re-uploads, and
    alternate versions or mixes the query didn't ask for are penalized.
    """
    title = str(entry.get("title") or "").lower()
    channel = str(entry.get("channel") or entry.get("uploader") or "").lower()
    query = query.lower()
    cleaned = clean_title(title)
    query_words = clean_title(query)
    # A query that is a subset of the title's words still scores fully, so the
    # artist/length/popularity signals decide between near-identical titles
    score = max(
        fuzz.token_set_ratio(query_words, cleaned),
        fuzz.token_set_ratio(query_words, f"{channel} {cleaned}"),
    )
    score -= rank * RANK_PENALTY

    music_rank = (music_ids or {}).get(entry.get("id") or _video_id(entry.get("url")))
    if music_rank is not None:
        score += MUSIC_BONUS + max(0, 3 - music_rank) * MUSIC_RANK_BONUS
    if channel.endswith("- topic"):
        score += TOPIC_BONUS
    if entry.get("channel_is_verified"):
        score += VERIFIED_BONUS
    if "official" in title:
        score += OFFICIAL_BONUS

    views = entry.get("view_count") or 0
    score += min(VIEWS_CAP, VIEWS_WEIGHT * math.log10(views + 1))

    score -= OFF_VERSION_PENALTY * len(off_version_words(title, query))
    requested = {w for w in OFF_VERSION_WORDS if re.search(rf"\b{w}\b", query)}
    score += REQUESTED_VERSION_BONUS * len(requested - off_version_words(query, title))
    score += length_adjustment(entry.get("duration"))
    score += artist_adjustment(title, channel)
    return score


def length_adjustment(duration) -> float:
    """Favor song-length videos over clips, long edits and mixes."""
    if not duration:
        return 0
    if SONG_SECONDS[0] <= duration <= SONG_SECONDS[1]:
        return LENGTH_BONUS
    if duration > MIX_SECONDS:
        return -MIX_PENALTY
    if not ACCEPTABLE_SECONDS[0] <= duration <= ACCEPTABLE_SECONDS[1]:
        return -LENGTH_PENALTY
    return 0


def artist_adjustment(title: str, channel: str) -> float:
    """Favor uploads that name an artist: 'Artist - Title', or an artist's own channel."""
    bonus = 0
    if re.match(r"^[^-\u2013\u2014|]{2,60}\s[-\u2013\u2014]\s+\S", title):
        bonus += ARTIST_TITLE_BONUS
    artist = re.sub(r"\s*(-\s*topic|vevo|official)\b", "", channel).strip()
    if len(artist) >= 3 and fuzz.partial_ratio(artist, title) >= 90:
        bonus += ARTIST_CHANNEL_BONUS
    if "vevo" in channel:
        bonus += VEVO_BONUS
    return bonus


def best_match(
    query: str, entries: list[dict], music_ids: dict[str, int] | None = None
) -> dict | None:
    """Pick the most likely intended song from search results."""
    candidates = [e for e in entries if e and not _is_live(e)]
    scored = [
        (score_entry(query, entry, rank, music_ids), entry)
        for rank, entry in enumerate(candidates)
    ]
    return max(scored, key=lambda pair: pair[0])[1] if scored else None


def _watch_url(entry: dict) -> str | None:
    """Return the watch-page URL for a yt-dlp entry."""
    url = entry.get("webpage_url") or entry.get("url")
    if url and URL_PATTERN.fullmatch(url):
        return url
    if entry.get("id"):
        return f"https://www.youtube.com/watch?v={entry['id']}"
    return None


def is_playlist_url(url: str) -> bool:
    """Return whether a link points at a playlist or album rather than one video."""
    parsed = urllib.parse.urlparse(url.strip())
    query = urllib.parse.parse_qs(parsed.query)
    if "list" not in query or "v" in query:
        # A watch link carrying a list is a video shared from that list
        return False
    # Radio/mix lists are endless and personalized
    return not query["list"][0].startswith(("RD", "UL"))


def _extract(target: str, flat: bool = False, playlist: bool = False) -> dict:
    """Run a blocking yt-dlp lookup."""
    options = {**YDL_OPTIONS, "extract_flat": "in_playlist"} if flat else YDL_OPTIONS
    options = {**options, "noplaylist": not playlist, "playlistend": MAX_PLAYLIST}
    if cookie_file:
        options["cookiefile"] = cookie_file
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            return ydl.extract_info(target, download=False)
    except yt_dlp.utils.DownloadError as e:
        logger.warning(f"yt-dlp failed for {target!r}: {e}")
        raise MusicError("Couldn't load that from YouTube.") from e


async def load_link(url: str, requester: str) -> Track:
    """Load one video from a link; playlist links use their first video."""
    info = await asyncio.to_thread(_extract, url)
    entries = info.get("entries")
    entry = next((e for e in entries if e), None) if entries else info
    return _track_from(entry, url, requester)


def _track_from(entry: dict | None, query: str, requester: str) -> Track:
    """Build a Track from a yt-dlp entry, or raise a user-facing error."""
    link = _watch_url(entry) if entry else None
    if entry is None or link is None or not entry.get("title"):
        raise MusicError(f"No playable results for `{query[:100]}`.")
    if _is_live(entry):
        raise MusicError("Live streams can't be queued.")
    return Track(
        title=entry["title"],
        url=link,
        duration=entry.get("duration"),
        requester=requester,
    )


async def load_playlist(url: str, requester: str) -> tuple[str, list[Track]]:
    """Load a playlist or album's playable tracks, capped at MAX_PLAYLIST."""
    info = await asyncio.to_thread(_extract, url, True, True)
    tracks = []
    for entry in info.get("entries") or []:
        if not entry or str(entry.get("title") or "").lower() in UNAVAILABLE_TITLES:
            continue
        try:
            tracks.append(_track_from(entry, url, requester))
        except MusicError:
            continue
    if not tracks:
        raise MusicError("That playlist has no playable songs.")
    return str(info.get("title") or "playlist"), tracks[:MAX_PLAYLIST]


async def _music_ids(query: str) -> dict[str, int]:
    """Map video IDs in YouTube Music's top results to their rank; empty on failure."""
    url = "https://music.youtube.com/search?q=" + urllib.parse.quote(query)
    try:
        info = await asyncio.to_thread(_extract, url, True)
    except MusicError:
        return {}
    ids = {}
    for entry in info.get("entries") or []:
        video = _video_id(entry.get("url")) if entry else None
        if video and video not in ids:
            ids[video] = len(ids)
    return {video: rank for video, rank in ids.items() if rank < MUSIC_RESULTS}


async def find_track(query: str, requester: str, pin: Pin | None = None) -> Track:
    """Resolve a link, a pinned match, or the likeliest YouTube song into a Track."""
    query = query.strip()
    if not query:
        raise MusicError("Give me a song name or a link.")
    if is_url(query):
        return await load_link(query, requester)
    if pin is not None:
        return Track(pin.title, pin.url, pin.duration, requester, pinned=True)
    search = asyncio.to_thread(_extract, f"ytsearch{SEARCH_RESULTS}:{query}", True)
    info, music_ids = await asyncio.gather(search, _music_ids(query))
    entry = best_match(query, info.get("entries") or [], music_ids)
    return _track_from(entry, query, requester)


def _extract_stream(url: str) -> str:
    """Return a fresh direct audio stream URL for a watch page."""
    info = _extract(url)
    entries = info.get("entries")
    if entries:
        info = next((e for e in entries if e), info)
    stream = info.get("url")
    if not stream:
        raise MusicError("No audio stream found.")
    return stream


class GuildPlayer:
    """Queue and playback state for one server's voice connection."""

    def __init__(self, guild: discord.Guild):
        """Create an idle player; must be built inside the running event loop."""
        self.guild = guild
        self.loop = asyncio.get_running_loop()
        self.queue: deque[Track] = deque()
        self.current: Track | None = None
        self.text_channel = None
        # Set while the next track's stream URL is being resolved
        self._task: asyncio.Task | None = None

    @property
    def voice(self) -> discord.VoiceClient | None:
        """Return the server's live voice client, if connected."""
        return self.guild.voice_client

    @property
    def busy(self) -> bool:
        """Return whether a track is playing, paused, or about to start."""
        voice = self.voice
        return self._task is not None or bool(
            voice and (voice.is_playing() or voice.is_paused())
        )

    @property
    def paused(self) -> bool:
        """Return whether playback is paused."""
        return bool(self.voice and self.voice.is_paused())

    def add(self, track: Track, text_channel=None) -> int:
        """Queue a track and start it if idle; return its 1-based queue position, or 0 if playing."""
        if len(self.queue) >= MAX_QUEUE:
            raise MusicError(f"The queue is full ({MAX_QUEUE} songs).")
        self.text_channel = text_channel or self.text_channel
        self.queue.append(track)
        self._start_next()
        return 0 if self.current is track else len(self.queue)

    def pause(self) -> bool:
        """Pause the playing track; return whether anything was paused."""
        if self.voice and self.voice.is_playing():
            self.voice.pause()
            return True
        return False

    def resume(self) -> bool:
        """Resume a paused track; return whether anything was resumed."""
        if self.paused:
            self.voice.resume()
            return True
        return False

    def skip(self) -> Track | None:
        """Skip the current track and return it, or None if nothing was playing."""
        skipped = self.current
        if skipped is None:
            return None
        if self._task is not None:
            self._cancel_pending()
            self.current = None
            self._start_next(announce=True)
        elif self.voice:
            # The after-callback advances to the next track
            self.voice.stop()
        return skipped

    def clear(self) -> int:
        """Drop all queued tracks, keeping the current one; return how many."""
        count = len(self.queue)
        self.queue.clear()
        return count

    def stop(self) -> None:
        """Clear the queue and stop the current track."""
        self.clear()
        if self._task is not None:
            self._cancel_pending()
            self.current = None
        if self.voice:
            self.voice.stop()

    async def disconnect(self) -> None:
        """Stop playback and leave the voice channel."""
        self.stop()
        if self.voice:
            await self.voice.disconnect()

    def _cancel_pending(self) -> None:
        """Abort a track that is still resolving its stream URL."""
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def _start_next(self, announce: bool = False) -> None:
        """Start the next queued track when connected and idle."""
        voice = self.voice
        if voice is None or not voice.is_connected() or self.busy:
            return
        if not self.queue:
            self.current = None
            return
        self.current = self.queue.popleft()
        self._task = self.loop.create_task(self._play(self.current, announce))

    async def _play(self, track: Track, announce: bool) -> None:
        """Resolve a track's stream and hand it to the voice client."""
        failure = None
        try:
            stream = await asyncio.to_thread(_extract_stream, track.url)
            source = discord.FFmpegPCMAudio(stream, **FFMPEG_OPTIONS)
            self.voice.play(source, after=lambda error: self._after(track, error))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Could not start {track.title!r}", exc_info=e)
            failure = e
        finally:
            if self._task is asyncio.current_task():
                self._task = None
        if failure is not None:
            if self.current is track:
                self.current = None
            await self._notify(f"❌ Couldn't play **{_clean(track.title)}**.")
            self._start_next(announce=True)
        elif announce:
            await self._notify(f"▶️ Now playing **{_clean(track.title)}**.")

    def _after(self, track: Track, error) -> None:
        """Voice-thread callback: hop back onto the event loop."""
        self.loop.call_soon_threadsafe(self._finished, track, error)

    def _finished(self, track: Track, error) -> None:
        """Advance the queue once a track ends, unless it was already replaced."""
        if error:
            logger.error(f"Playback error for {track.title!r}: {error!r}")
        if self.current is not track:
            return
        self.current = None
        self._start_next(announce=True)

    async def _notify(self, message: str) -> None:
        """Post a status line to the last channel used, ignoring send failures."""
        if self.text_channel is None:
            return
        try:
            await self.text_channel.send(
                message, allowed_mentions=discord.AllowedMentions.none()
            )
        except discord.HTTPException:
            logger.debug("Could not send music notice", exc_info=True)


def _clean(title: str) -> str:
    """Escape markdown in a track title."""
    return discord.utils.escape_markdown(title)


class MusicManager:
    """Per-server players, shared across command-module reloads."""

    def __init__(self, drive=None):
        """Create an empty manager; pins persist when a drive is supplied."""
        self.players: dict[int, GuildPlayer] = {}
        self.pins = PinStore(drive)

    def player(self, guild: discord.Guild) -> GuildPlayer:
        """Return the server's player, creating it on first use."""
        if guild.id not in self.players:
            self.players[guild.id] = GuildPlayer(guild)
        return self.players[guild.id]

    def drop(self, guild: discord.Guild) -> None:
        """Forget a server's player."""
        self.players.pop(guild.id, None)

    @staticmethod
    def user_channel(interaction: discord.Interaction):
        """Return the voice channel the command user is in, or raise."""
        voice = getattr(interaction.user, "voice", None)
        if voice is None or voice.channel is None:
            raise MusicError("Join a voice channel first.")
        return voice.channel

    async def connect(self, guild: discord.Guild, channel) -> discord.VoiceClient:
        """Join or move to a voice channel, refusing to pull the bot off active playback."""
        me = guild.me
        permissions = channel.permissions_for(me)
        if not (permissions.connect and permissions.speak):
            raise MusicError(
                f"I need Connect and Speak permissions in {channel.mention}."
            )
        voice = guild.voice_client
        if voice is None:
            return await channel.connect(self_deaf=True)
        if voice.channel != channel:
            if self.player(guild).busy:
                raise MusicError(f"I'm already playing in {voice.channel.mention}.")
            await voice.move_to(channel)
        return voice

    def control_player(self, interaction: discord.Interaction) -> GuildPlayer:
        """Return the player for a user who shares the bot's voice channel, or raise."""
        voice = interaction.guild.voice_client
        if voice is None:
            raise MusicError("I'm not in a voice channel.")
        if self.user_channel(interaction) != voice.channel:
            raise MusicError(f"Join {voice.channel.mention} to control the music.")
        return self.player(interaction.guild)


def get_manager(client) -> MusicManager:
    """Return the bot's music manager, creating it once."""
    global cookie_file
    cookie_file = getattr(client, "ytdl_cookies", None)
    if getattr(client, "music", None) is None:
        client.music = MusicManager(getattr(client, "drive", None))
    return client.music
