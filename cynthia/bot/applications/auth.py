import re
import discord
from discord import app_commands
from typing import Union

PERMS = ("privileged", "nxbt", "drive", "admins", "owners")
VIEW_ORDER = ("owners", "admins", "privileged", "nxbt", "drive")

# Lists editable inside a guild, and which guild-level lists may edit them
GUILD_EDITORS = {
    "privileged": ("privileged", "admins", "owners"),
    "admins": ("admins", "owners"),
    "owners": ("owners",),
}

PERM_CHOICES = [app_commands.Choice(name=p, value=p) for p in PERMS]
SCOPE_CHOICES = [
    app_commands.Choice(name="guild", value="guild"),
    app_commands.Choice(name="global", value="global"),
]

NO_PINGS = discord.AllowedMentions.none()


async def reply(interaction: discord.Interaction, content=None, **kwargs):
    await interaction.response.send_message(
        content, ephemeral=True, allowed_mentions=NO_PINGS, **kwargs
    )


def can_edit(interaction: discord.Interaction, scope: str, perm: str) -> bool:
    client = interaction.client
    if scope == "global":
        return str(interaction.user.id) == client.owner
    if perm in GUILD_EDITORS:
        return any(client.perms_check(interaction, perm=p) for p in GUILD_EDITORS[perm])
    # nxbt, drive and allowed_commands need a global owner
    return client.permsloader.is_global(interaction.user.id, "owners")


def required_text(scope: str, perm: str) -> str:
    if scope == "global":
        return "the bot owner"
    if perm in GUILD_EDITORS:
        return " or ".join(f"`{p}`" for p in GUILD_EDITORS[perm]) + " in this server"
    return "a global `owners`"


def resolve_context(interaction: discord.Interaction, scope: str):
    """Return the permissions context key to edit, or None if unavailable."""
    client = interaction.client
    if scope == "global":
        return "global"
    if interaction.guild_id is None:
        return None
    key, ctx = client.permsloader.ensure_guild(interaction.guild_id)
    # bot.perms is what gets written at shutdown, so keep it in step
    client.perms[key] = ctx
    return key


def persist(interaction: discord.Interaction):
    interaction.client.permsloader.save(interaction.client.perms.dict())


def describe_entry(entry) -> str:
    match = re.fullmatch(r"([+-]?)([urg]):(\w+)", str(entry))
    if match is None:
        return f"`{entry}`"
    sign, kind, uid = match.groups()
    if kind == "u":
        who = f"<@{uid}>"
    elif kind == "r":
        who = f"<@&{uid}>"
    else:
        who = "Entire server"
    return f"🚫 {who} (denied)" if sign == "-" else who


def field_text(lines: list[str]) -> str:
    if not lines:
        return "—"
    text = ""
    for idx, line in enumerate(lines):
        if len(text) + len(line) + 30 > 1024:
            return text + f"…and {len(lines) - idx} more"
        text += line + "\n"
    return text.strip()


def target_parts(target):
    if isinstance(target, discord.Role):
        return "r", target.id
    return "u", target.id


@app_commands.command()
@app_commands.describe(scope="Which permissions to show (global is bot owner only)")
@app_commands.choices(scope=SCOPE_CHOICES)
async def perms_view(
    interaction: discord.Interaction, scope: app_commands.Choice[str] = None
):
    scope = scope.value if scope else "guild"
    client = interaction.client
    if scope == "global":
        if str(interaction.user.id) != client.owner:
            return await reply(
                interaction, "Only the bot owner can view global permissions."
            )
        title = "Global permissions"
    else:
        if interaction.guild is None:
            return await reply(
                interaction, "Use this in a server, or choose scope `global`."
            )
        title = f"Permissions for {interaction.guild.name}"
    context = resolve_context(interaction, scope)
    perms = client.perms[context]

    embed = discord.Embed(title=title, color=0xD700FF)
    for perm in VIEW_ORDER:
        embed.add_field(
            name=perm,
            value=field_text([describe_entry(e) for e in perms[perm]]),
            inline=False,
        )
    embed.add_field(
        name="allowed commands",
        value=field_text([f"`/{c}`" for c in perms["allowed_commands"]]),
        inline=False,
    )
    if scope == "guild":
        embed.set_footer(text="Global permissions also apply in every server.")
    await reply(interaction, embed=embed)


@app_commands.command()
@app_commands.describe(
    perm="Permission to grant",
    target="User or role to grant it to",
    deny="Explicitly deny instead of allow (deny overrides allow)",
    scope="Server (default) or global (bot owner only, users only)",
)
@app_commands.choices(perm=PERM_CHOICES, scope=SCOPE_CHOICES)
async def perms_grant(
    interaction: discord.Interaction,
    perm: app_commands.Choice[str],
    target: Union[discord.User, discord.Member, discord.Role],
    deny: bool = False,
    scope: app_commands.Choice[str] = None,
):
    await edit_perm(interaction, perm.value, target, scope, grant=True, deny=deny)


@app_commands.command()
@app_commands.describe(
    perm="Permission to remove",
    target="User or role to remove it from",
    scope="Server (default) or global (bot owner only, users only)",
)
@app_commands.choices(perm=PERM_CHOICES, scope=SCOPE_CHOICES)
async def perms_revoke(
    interaction: discord.Interaction,
    perm: app_commands.Choice[str],
    target: Union[discord.User, discord.Member, discord.Role],
    scope: app_commands.Choice[str] = None,
):
    await edit_perm(interaction, perm.value, target, scope, grant=False)


async def edit_perm(interaction, perm, target, scope, *, grant, deny=False):
    scope = scope.value if scope else "guild"
    client = interaction.client
    kind, uid = target_parts(target)

    if not can_edit(interaction, scope, perm):
        return await reply(
            interaction,
            f"You need {required_text(scope, perm)} to edit `{perm}` permissions.",
        )
    if scope == "global" and kind == "r":
        return await reply(interaction, "Roles can't be used for global permissions.")
    if kind == "u" and str(uid) == client.owner:
        return await reply(interaction, "The bot owner's permissions can't be changed.")
    context = resolve_context(interaction, scope)
    if context is None:
        return await reply(
            interaction, "Use this in a server, or choose scope `global`."
        )

    loader = client.permsloader
    name = f"<@&{uid}>" if kind == "r" else f"<@{uid}>"
    where = "globally" if scope == "global" else "in this server"
    if grant:
        result = loader.grant(context, perm, kind, uid, allow=not deny)
        verb = "Denied" if deny else "Granted"
        message = (
            f"{name} already has that entry for `{perm}`."
            if result == "unchanged"
            else f"{verb} `{perm}` {'to' if not deny else 'for'} {name} {where}."
        )
    else:
        removed = loader.revoke(context, perm, kind, uid)
        message = (
            f"Removed {name} from `{perm}` {where}."
            if removed
            else f"{name} has no `{perm}` entry {where}."
        )
    try:
        persist(interaction)
    except OSError as e:
        message += f"\n⚠️ Applied, but saving perms.yaml failed: {e}"
    await reply(interaction, message)


def command_names(interaction: discord.Interaction) -> list[str]:
    return sorted(c.name for c in interaction.client.tree.get_commands())


async def allow_autocomplete(interaction: discord.Interaction, current: str):
    scope = getattr(interaction.namespace, "scope", None) or "guild"
    if scope == "guild" and interaction.guild_id is None:
        return []
    key = "global" if scope == "global" else resolve_context(interaction, scope)
    current_list = interaction.client.perms[key]["allowed_commands"]
    return [
        app_commands.Choice(name=n, value=n)
        for n in command_names(interaction)
        if current.lower().lstrip("/") in n and n not in current_list
    ][:25]


async def disallow_autocomplete(interaction: discord.Interaction, current: str):
    scope = getattr(interaction.namespace, "scope", None) or "guild"
    if scope == "guild" and interaction.guild_id is None:
        return []
    key = "global" if scope == "global" else resolve_context(interaction, scope)
    return [
        app_commands.Choice(name=n, value=n)
        for n in interaction.client.perms[key]["allowed_commands"]
        if current.lower().lstrip("/") in n
    ][:25]


@app_commands.command()
@app_commands.describe(
    command="Command to allow",
    scope="Server (default) or global (bot owner only)",
)
@app_commands.choices(scope=SCOPE_CHOICES)
async def command_allow(
    interaction: discord.Interaction,
    command: str,
    scope: app_commands.Choice[str] = None,
):
    await edit_command(interaction, command, scope, allow=True)


@app_commands.command()
@app_commands.describe(
    command="Command to disallow",
    scope="Server (default) or global (bot owner only)",
)
@app_commands.choices(scope=SCOPE_CHOICES)
async def command_disallow(
    interaction: discord.Interaction,
    command: str,
    scope: app_commands.Choice[str] = None,
):
    await edit_command(interaction, command, scope, allow=False)


command_allow.autocomplete("command")(allow_autocomplete)
command_disallow.autocomplete("command")(disallow_autocomplete)


async def edit_command(interaction, command, scope, *, allow):
    scope = scope.value if scope else "guild"
    command = command.strip().lstrip("/")

    if not can_edit(interaction, scope, "allowed_commands"):
        return await reply(
            interaction,
            f"You need {required_text(scope, 'allowed_commands')} to edit allowed commands.",
        )
    context = resolve_context(interaction, scope)
    if context is None:
        return await reply(
            interaction, "Use this in a server, or choose scope `global`."
        )
    if allow and interaction.client.tree.get_command(command) is None:
        return await reply(interaction, f"No command named `/{command}` exists.")

    loader = interaction.client.permsloader
    where = "globally" if scope == "global" else "in this server"
    if allow:
        changed = loader.allow_command(context, command)
        message = (
            f"`/{command}` is now allowed {where}."
            if changed
            else f"`/{command}` is already allowed {where}."
        )
    else:
        changed = loader.disallow_command(context, command)
        message = (
            f"`/{command}` is no longer allowed {where}."
            if changed
            else f"`/{command}` wasn't in the allowed list {where}."
        )
    try:
        persist(interaction)
    except OSError as e:
        message += f"\n⚠️ Applied, but saving perms.yaml failed: {e}"
    await reply(interaction, message)


__application__ = [
    perms_view,
    perms_grant,
    perms_revoke,
    command_allow,
    command_disallow,
]
