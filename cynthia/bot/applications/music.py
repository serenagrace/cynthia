"""Discord slash commands for playing YouTube audio in voice calls."""

import discord
from discord import app_commands

from cynthia.utils.auth import require_command_allowed
from cynthia.utils.music import (
    MusicError,
    Pin,
    Track,
    find_track,
    format_duration,
    get_manager,
    is_playlist_url,
    is_url,
    load_link,
    load_playlist,
)

QUEUE_PAGE = 10
NO_MENTIONS = discord.AllowedMentions.none()


def track_line(track: Track) -> str:
    """Format a track as a linked title with its duration."""
    title = discord.utils.escape_markdown(track.title).replace("]", "\\]")
    return f"[{title}]({track.url}) `{format_duration(track.duration)}`"


async def reply(interaction: discord.Interaction, content=None, *, embed=None):
    """Send a deferred response that can never ping anyone."""
    await interaction.followup.send(content, embed=embed, allowed_mentions=NO_MENTIONS)


class MusicGroup(app_commands.Group):
    """Voice-call music commands, usable only in servers that allow `/music`."""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Require `music` in the server's allowed commands."""
        return require_command_allowed(interaction, self.name)


music = MusicGroup(
    name="music",
    description="Play songs from YouTube in your voice channel.",
    guild_only=True,
)


async def enqueue(interaction: discord.Interaction, query: str):
    """Find a song, join the user's channel, and queue it."""
    manager = get_manager(interaction.client)
    channel = manager.user_channel(interaction)
    await interaction.response.defer()
    if is_url(query) and is_playlist_url(query):
        await enqueue_playlist(interaction, manager, channel, query.strip())
        return
    pin = None if is_url(query) else manager.pins.match(interaction.guild_id, query)
    track = await find_track(query, interaction.user.display_name, pin)
    await manager.connect(interaction.guild, channel)
    player = manager.player(interaction.guild)
    position = player.add(track, interaction.channel)
    if position == 0:
        title = "▶️ Now playing"
    else:
        title = f"➕ Queued at position {position}"
    if track.pinned:
        title += " (📌 pinned)"
    embed = discord.Embed(title=title, description=track_line(track))
    embed.set_footer(text=f"Requested by {interaction.user.display_name}")
    await reply(interaction, embed=embed)


async def enqueue_playlist(interaction, manager, channel, url: str):
    """Queue every playable song in a playlist or album link."""
    name, tracks = await load_playlist(url, interaction.user.display_name)
    await manager.connect(interaction.guild, channel)
    player = manager.player(interaction.guild)
    added = 0
    for track in tracks:
        try:
            player.add(track, interaction.channel)
        except MusicError:
            break
        added += 1
    skipped = len(tracks) - added
    description = f"**{discord.utils.escape_markdown(name)}**: {added} songs queued."
    if skipped:
        description += f" The queue filled up, so {skipped} were left out."
    embed = discord.Embed(title="➕ Playlist queued", description=description)
    embed.set_footer(text=f"Requested by {interaction.user.display_name}")
    await reply(interaction, embed=embed)


@music.command(name="play")
@app_commands.describe(
    query="A YouTube or YouTube Music link or playlist, or words to search for. Empty resumes."
)
async def play(interaction: discord.Interaction, query: str | None = None):
    """Queue a song from a link or search and play it in your voice channel."""
    if query is None:
        manager = get_manager(interaction.client)
        player = manager.control_player(interaction)
        if not player.resume():
            raise MusicError("Give me a song name or a link to play.")
        await interaction.response.send_message("▶️ Resumed.")
        return
    await enqueue(interaction, query)


@music.command(name="search")
@app_commands.describe(query="Words to search YouTube for")
async def search(interaction: discord.Interaction, query: str):
    """Search YouTube for the closest song match, queue it, and play it."""
    await enqueue(interaction, query)


@music.command(name="pause")
async def pause(interaction: discord.Interaction):
    """Pause the current song. Use /music play with no query to resume."""
    player = get_manager(interaction.client).control_player(interaction)
    if not player.pause():
        raise MusicError("Nothing is playing.")
    await interaction.response.send_message("⏸️ Paused.")


@music.command(name="skip")
async def skip(interaction: discord.Interaction):
    """Skip the current song."""
    player = get_manager(interaction.client).control_player(interaction)
    skipped = player.skip()
    if skipped is None:
        raise MusicError("Nothing is playing.")
    await interaction.response.send_message(
        f"⏭️ Skipped **{discord.utils.escape_markdown(skipped.title)}**.",
        allowed_mentions=NO_MENTIONS,
    )


@music.command(name="stop")
async def stop(interaction: discord.Interaction):
    """Stop playback and clear the queue, staying in the channel."""
    player = get_manager(interaction.client).control_player(interaction)
    player.stop()
    await interaction.response.send_message("⏹️ Stopped and cleared the queue.")


@music.command(name="queue")
async def queue(interaction: discord.Interaction):
    """Show the current song and what's queued."""
    manager = get_manager(interaction.client)
    player = manager.players.get(interaction.guild_id)
    if player is None or (player.current is None and not player.queue):
        await interaction.response.send_message("The queue is empty.")
        return
    embed = discord.Embed(title="🎶 Queue")
    if player.current is not None:
        state = "Paused" if player.paused else "Now playing"
        embed.add_field(name=state, value=track_line(player.current), inline=False)
    upcoming = list(player.queue)
    if upcoming:
        lines = [
            f"`{index}.` {track_line(track)}"
            for index, track in enumerate(upcoming[:QUEUE_PAGE], start=1)
        ]
        if len(upcoming) > QUEUE_PAGE:
            lines.append(f"…and {len(upcoming) - QUEUE_PAGE} more")
        embed.add_field(name="Up next", value="\n".join(lines), inline=False)
        known = sum(track.duration or 0 for track in upcoming)
        embed.set_footer(
            text=f"{len(upcoming)} queued · {format_duration(known)} total"
        )
    await interaction.response.send_message(embed=embed, allowed_mentions=NO_MENTIONS)


@music.command(name="clear")
async def clear(interaction: discord.Interaction):
    """Remove all queued songs, leaving the current one playing."""
    player = get_manager(interaction.client).control_player(interaction)
    count = player.clear()
    await interaction.response.send_message(
        f"🗑️ Cleared {count} song{'' if count == 1 else 's'} from the queue."
    )


@music.command(name="pin")
@app_commands.describe(
    link="The YouTube link to return for matching searches",
    query="What people search to find it (defaults to the song's title)",
)
async def pin(interaction: discord.Interaction, link: str, query: str | None = None):
    """Pin a link so searches that resemble it play that exact song first."""
    if not is_url(link):
        raise MusicError("Pin needs a YouTube link.")
    manager = get_manager(interaction.client)
    await interaction.response.defer()
    track = await load_link(link, interaction.user.display_name)
    alias = (query or "").strip() or track.title
    replaced = manager.pins.add(
        interaction.guild_id,
        Pin(
            title=track.title,
            url=track.url,
            duration=track.duration,
            query=alias,
            pinned_by=interaction.user.display_name,
        ),
    )
    verb = "Updated pin" if replaced else "Pinned"
    note = (
        "" if manager.pins.drive else "\n-# Pins reset on restart: no drive configured."
    )
    await reply(
        interaction,
        f"📌 {verb}: {track_line(track)}\nSearches like `{alias}` now play it first.{note}",
    )


@music.command(name="unpin")
@app_commands.describe(number="Pin number from /music pins")
async def unpin(interaction: discord.Interaction, number: int):
    """Remove a pinned song."""
    removed = get_manager(interaction.client).pins.remove(interaction.guild_id, number)
    if removed is None:
        raise MusicError("No pin with that number. Check /music pins.")
    await interaction.response.send_message(
        f"Unpinned **{discord.utils.escape_markdown(removed.title)}**.",
        allowed_mentions=NO_MENTIONS,
    )


@music.command(name="pins")
async def pins(interaction: discord.Interaction):
    """List this server's pinned songs."""
    pinned = get_manager(interaction.client).pins.list(interaction.guild_id)
    if not pinned:
        await interaction.response.send_message(
            "No pins yet. Add one with `/music pin`."
        )
        return
    lines = [
        f"`{index}.` {discord.utils.escape_markdown(p.title)} — "
        f"matches `{p.query[:60]}` · by {discord.utils.escape_markdown(p.pinned_by)}"
        for index, p in enumerate(pinned, start=1)
    ]
    embed = discord.Embed(title="📌 Pinned songs", description="\n".join(lines)[:4000])
    await interaction.response.send_message(embed=embed, allowed_mentions=NO_MENTIONS)


@music.command(name="join")
async def join(interaction: discord.Interaction):
    """Join your voice channel."""
    manager = get_manager(interaction.client)
    channel = manager.user_channel(interaction)
    await interaction.response.defer()
    await manager.connect(interaction.guild, channel)
    await reply(interaction, f"🔊 Joined {channel.mention}.")


@music.command(name="leave")
async def leave(interaction: discord.Interaction):
    """Stop playback and leave the voice channel."""
    manager = get_manager(interaction.client)
    player = manager.control_player(interaction)
    await interaction.response.defer()
    await player.disconnect()
    manager.drop(interaction.guild)
    await reply(interaction, "👋 Left the voice channel.")


__application__ = music
