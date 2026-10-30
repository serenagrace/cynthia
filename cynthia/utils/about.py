"""Build the bot's shared about and startup embed."""

import discord

GITHUB_URL = "https://github.com/serenagrace/cynthia"


def build_about_embed(client, errors=None):
    """Return the shared about embed with startup metadata and load results."""
    errors = errors or []
    embed = discord.Embed(
        title=f"Cynthia ({client.app_meta.version})",
        description=f"View my [GitHub]({GITHUB_URL})",
        color=0xD700FF,
    )
    embed.set_author(
        name=client.user.name,
        icon_url=client.user.display_avatar.url,
    )
    embed.add_field(name="Launch Time:", value=f"{client.app_meta.run_timestamp}")
    embed.set_footer(
        text=f"#{client.app_meta.git_hash} {client.app_meta.git_timestamp}"
    )
    if client.loaded_command_count:
        embed.add_field(
            name="Loaded Commands:",
            value=f"{client.loaded_command_count} from {'⚠️' if len(client.tree.loaded_modules) != len(client.tree.modules) else ''}({len(client.tree.loaded_modules)}/{len(client.tree.modules)}) modules",
        )
    if client.loaded_cog_count:
        embed.add_field(
            name="Loaded Cogs:",
            value=f"{client.loaded_cog_count} from {'⚠️' if client.loaded_cog_count != len(client.discovered_cogs) else ''}({client.loaded_cog_count}/{len(client.discovered_cogs)}) modules",
        )
    if errors:
        embed.add_field(
            name="Errors:",
            value="-" + "\n-".join(errors[:3]) + ("\n..." if len(errors) > 3 else ""),
        )
    return embed
