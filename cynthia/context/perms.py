"""
Permissions Loader and handler.
"""

from pathlib import Path

import yaml

from cynthia.utils.snowflake import GuildFlake, PermFlake
from cynthia.utils.types import force_obj_is_dict, force_obj_is_list

from .defaults import Defaults

FLAKE_NAMES = {"u": "user", "r": "role"}


def guild_key(guild_id):
    """Format a guild ID as its permissions-context key."""
    return str(GuildFlake(str(guild_id)))


class PermsLoader:
    """Load, normalize, check, and persist user and guild permissions."""

    def __init__(self, filename):
        """Create a permissions loader for an existing file."""
        if not Path(filename).exists():
            raise FileNotFoundError("Specified perms file does not exist.")
        self.filename = filename

    @staticmethod
    def default():
        """Return the default permission lists."""
        return Defaults().perms

    def _load(self, bot):
        """Load permissions and build contexts for known and saved guilds."""
        with open(self.filename, "r") as f:
            self._file_perms = force_obj_is_dict(yaml.load(f, Loader=yaml.Loader))

        self._owner = (
            str(PermFlake(flake_type="user", uid=bot.owner, allow=True))
            if bot.owner
            else None
        )

        # Guild contexts are keyed by string ("g:<id>"), including guilds
        # saved in the file that the bot is no longer in
        contexts = ["global"] + [guild_key(guild.id) for guild in bot.guilds]
        contexts += [
            key
            for key in self._file_perms
            if isinstance(key, str) and key.startswith("g:") and key not in contexts
        ]

        return {ctx: self._build_context(self._file_perms.get(ctx)) for ctx in contexts}

    def _build_context(self, file_ctx=None):
        """Merge a saved context with defaults and include the configured owner."""
        # Fresh lists per context so edits to one guild never leak into another
        ctx_perms = {**self.default(), **force_obj_is_dict(file_ctx)}
        for privilege_list in ctx_perms:
            ctx_perms[privilege_list] = list(
                dict.fromkeys(force_obj_is_list(ctx_perms[privilege_list]))
            )
            if privilege_list == "allowed_commands":
                continue
            if self._owner is not None and self._owner not in ctx_perms[privilege_list]:
                ctx_perms[privilege_list].append(self._owner)
        return ctx_perms

    def ensure_guild(self, guild_id):
        """Return the permissions context for a guild, creating it if needed."""
        key = guild_key(guild_id)
        if key not in self._perms:
            self._perms[key] = self._build_context()
        return key, self._perms[key]

    @staticmethod
    def _entry_target(entry):
        """Return a permission entry without its allow or deny prefix."""
        return str(entry).lstrip("+-")

    def grant(self, context, perm, kind, uid, *, allow=True):
        """Add a +/- entry for a user ("u") or role ("r"). Returns the change made."""
        entries = self._perms[context][perm]
        new = str(PermFlake(flake_type=FLAKE_NAMES[kind], uid=str(uid), allow=allow))
        if new in entries:
            return "unchanged"
        target = f"{kind}:{uid}"
        existing = [e for e in entries if self._entry_target(e) == target]
        for entry in existing:
            entries.remove(entry)
        entries.append(new)
        return "updated" if existing else "added"

    def revoke(self, context, perm, kind, uid):
        """Remove a user's or role's permission entry; return whether one existed."""
        entries = self._perms[context][perm]
        target = f"{kind}:{uid}"
        kept = [e for e in entries if self._entry_target(e) != target]
        removed = len(kept) != len(entries)
        entries[:] = kept
        return removed

    def allow_command(self, context, command):
        """Allow a command in a context; return whether the list changed."""
        commands = self._perms[context]["allowed_commands"]
        if command in commands:
            return False
        commands.append(command)
        return True

    def disallow_command(self, context, command):
        """Remove a command allowance; return whether the list changed."""
        commands = self._perms[context]["allowed_commands"]
        if command not in commands:
            return False
        commands.remove(command)
        return True

    def is_global(self, user_id, perm):
        """Whether a user holds a permission in the global context alone."""
        return self.check_perm(
            user=user_id, guild="global", roles=[], ctx=None, perm=perm
        )

    def check(self, ctx, *, command=None, perm=None):
        """Check one permission or return all permissions for an interaction."""
        if perm == "allowed_commands":
            guild = getattr(ctx, "guild", None)
            return command in self._perms["global"]["allowed_commands"] or (
                guild is not None
                and command
                in self._perms.get(guild_key(guild.id), {}).get("allowed_commands", [])
            )
        user = ctx.user.id
        guild = (
            guild_key(ctx.guild_id)
            if getattr(ctx, "guild_id", None) is not None
            else "global"
        )
        roles = list()
        if guild != "global":
            roles = [role.id for role in ctx.user.roles]
        if perm is None:
            return {
                key: self.check_perm(
                    user=user, guild=guild, roles=roles, ctx=ctx, perm=key
                )
                for key in self._perms.get(guild, self._perms["global"]).keys()
            }
        else:
            return self.check_perm(
                user=user, guild=guild, roles=roles, ctx=ctx, perm=perm
            )

    def check_perm(
        self, *, user: str, guild: str, roles: list[str], ctx: str, perm: str
    ):
        """Resolve a permission across global, guild, role, and user rules."""
        # `guild` is "global" or a guild context key ("g:<id>")
        if perm not in self._perms["global"]:
            return False

        result = False
        checklist = list(self._perms["global"][perm])
        if guild != "global":
            checklist += self._perms.get(guild, {}).get(perm, [])
            guild_id = guild.split(":", 1)[1]
            if (
                str(PermFlake(flake_type="guild", uid=guild_id, allow=True))
                in checklist
            ):
                result = True
            if (
                str(PermFlake(flake_type="guild", uid=guild_id, allow=False))
                in checklist
            ):
                result = False
            if any(
                str(PermFlake(flake_type="role", uid=role, allow=True)) in checklist
                for role in roles
            ):
                result = True
            if any(
                str(PermFlake(flake_type="role", uid=role, allow=False)) in checklist
                for role in roles
            ):
                result = False
        if str(PermFlake(flake_type="user", uid=user, allow=True)) in checklist:
            result = True
        if str(PermFlake(flake_type="user", uid=user, allow=False)) in checklist:
            result = False
        return result

    def __call__(self, bot):
        """Return cached permissions, loading guild contexts on first access."""
        if not hasattr(self, "_perms"):
            self._perms = self._load(bot)
        return self._perms

    def save(self, updated_perms):
        """Write the supplied permissions mapping to the configured file."""
        with open(self.filename, "w") as f:
            yaml.dump(updated_perms, f)
