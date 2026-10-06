"""
Permissions Loader and handler.
"""

from pathlib import Path
import yaml
from cynthia.utils.types import force_obj_is_list, force_obj_is_dict
from cynthia.utils.snowflake import GuildFlake, PermFlake

from .defaults import Defaults


class PermsLoader:
    def __init__(self, filename):
        if not Path(filename).exists():
            raise FileNotFoundError("Specified perms file does not exist.")
        self.filename = filename

    @staticmethod
    def default():
        return Defaults().perms

    def _load(self, bot):
        perms = None
        with open(self.filename, "r") as f:
            self._file_perms = yaml.load(f, Loader=yaml.Loader)
            self._default_perms = self.default()
        # if perms is None:
        #    raise ValueError("Config file is empty or invalid.")

        privelege_contexts = ["global"] + [GuildFlake(guild.id) for guild in bot.guilds]

        perms = {
            ctx: {
                **self._default_perms,
                **force_obj_is_dict(self._file_perms).get(ctx, {}),
            }
            for ctx in privelege_contexts
        }

        owner = (
            PermFlake(flake_type="user", uid=bot.owner, allow=True)
            if bot.owner
            else None
        )

        for ctx in perms.keys():
            for privilege_list in perms[ctx].keys():
                if privilege_list == "allowed_commands":
                    continue
                perms[ctx][privilege_list] = force_obj_is_list(
                    perms[ctx][privilege_list]
                )
                if owner is not None:
                    if owner not in perms[ctx][privilege_list]:
                        perms[ctx][privilege_list].append(str(owner))

        return perms

    def check(self, ctx, *, command=None, perm=None):
        if perm == "allowed_commands":
            return command in self._perms["global"]["allowed_commands"] or (
                getattr(ctx, "guild", None) is not None
                and command in self._perms[GuildFlake(ctx.guild.id)]["allowed_commands"]
            )
        user = ctx.user.id
        guild = ctx.guild_id if getattr(ctx, "guild_id", None) is not None else "global"
        roles = list()
        if guild != "global":
            roles = [role.id for role in ctx.user.roles]
        if perm is None:
            return {
                key: self.check_perm(
                    user=user, guild=guild, roles=roles, ctx=ctx, perm=key
                )
                for key in self._perms[guild].keys()
            }
        else:
            return self.check_perm(
                user=user, guild=guild, roles=roles, ctx=ctx, perm=perm
            )

    def check_perm(
        self, *, user: str, guild: str, roles: list[str], ctx: str, perm: str
    ):
        if guild not in self._perms:
            return False
        if perm not in self._perms[guild]:
            return False

        result = False
        checklist = self._perms["global"][perm]
        if guild != "global":
            checklist += self._perms[GuildFlake(guild)][perm]
            if str(PermFlake(flake_type="guild", uid=guild, allow=True)) in checklist:
                result = True
            if str(PermFlake(flake_type="guild", uid=guild, allow=False)) in checklist:
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
        if not hasattr(self, "_perms"):
            self._perms = self._load(bot)
        return self._perms

    def save(self, updated_perms):
        with open(self.filename, "w") as f:
            yaml.dump(updated_perms, f)
