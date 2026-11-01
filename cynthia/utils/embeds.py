"""Shared look for command-response embeds."""

import discord

# Cynthia's accent, also used by /about and /status
BRAND = 0xD700FF
LIVE = 0xEB0400
OFFLINE = 0x747F8D
TWITCH = 0x9146FF


def make_embed(title=None, description=None, *, color=BRAND, url=None, fields=()):
    """Build an embed; `fields` holds (name, value) or (name, value, inline)."""
    embed = discord.Embed(title=title, description=description, color=color, url=url)
    for field in fields:
        name, value, *inline = field
        embed.add_field(name=name, value=value, inline=inline[0] if inline else True)
    return embed


def image_embed(title, filename, *, color=BRAND, fields=()):
    """An embed that shows the attachment `filename` as its image."""
    embed = make_embed(title, color=color, fields=fields)
    embed.set_image(url=f"attachment://{filename}")
    return embed
