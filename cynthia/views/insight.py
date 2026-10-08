import discord
from datetime import datetime, timezone, timedelta
from cynthia.utils.auth import button_requires_permission
from cynthia.utils import Namespace
import re

SUSPICION_TYPES = {
    "account_age": "⚠️ Account is less than 6 months old.",
    "default_avatar": "⚠️ Default Avatar.",
    "username_digits": "⚠️ Username ends with a string of digits.",
    "rejoined": "⚠️ User has rejoined the server.",
    "suspicious_roles": "⚠️ User has one or more suspicious roles.",
    "flagged_spammer": "⚠️ User is flagged as a spammer.",
}


class Suspicions(Namespace):
    def __init__(self):
        super().__init__({k: False for k in SUSPICION_TYPES.keys()})

    def __iter__(self):
        for k, v in self._nspace_dict.items():
            if v:
                yield SUSPICION_TYPES[k]

    def __len__(self):
        return sum(1 for v in self._nspace_dict.values() if v)


class InsightView(discord.ui.LayoutView):
    VIEWS = {}

    def __init__(self, user, member):
        super().__init__(timeout=60 * 60 * 24)
        self.action_row = None

        self.suspicions = InsightView.gather_suspicions(user, member)

        self.message = None
        self.member = member
        self.user = user
        self.guild = member.guild
        self.voluntary_leave = True

        self.compile_view()
        self.status_section = None
        self._save_view()

    @staticmethod
    def build_sections(member, user, suspicions=None):

        if suspicions is None:
            suspicions = InsightView.gather_suspicions(user, member)

        # --- Title Section -----
        title_section = discord.ui.TextDisplay(
            content=f"**User Insight:** {user.mention}"
        )

        # --- User Section -----
        user_section = None
        user_section = discord.ui.Section(
            f"**Created:** {discord.utils.format_dt(user.created_at, style='R')}",
            f"**Joined:** {discord.utils.format_dt(member.joined_at, style='R')}",
            f"**User ID:** `{user.id}`",
            accessory=discord.ui.Thumbnail(member.display_avatar.url),
        )

        # --- Role Section -----
        role_section = None
        roles = [
            role.name
            for role in sorted(member.roles, reverse=True)
            if role.name != "@everyone" and role.name != "Default"
        ]
        if len(roles):
            roles_display = str()
            if len(roles) <= 3:
                roles_display = ", ".join(roles)
            else:
                roles_display = ", ".join(roles[:3]) + f", and {len(roles) - 3} more"
            role_section = discord.ui.TextDisplay(content=f"**Roles:** {roles_display}")

        # --- Analysis Section -----
        analysis_section = discord.ui.Container(
            discord.ui.TextDisplay(content="**Analysis:**")
        )
        for suspicion in suspicions:
            analysis_section.add_item(discord.ui.TextDisplay(content=suspicion))
        if len(suspicions) == 0:
            analysis_section.add_item(
                discord.ui.TextDisplay(content="✅ No suspicious activity detected.")
            )

        sections = list()
        for section in [title_section, user_section, role_section, analysis_section]:
            if section is not None:
                sections.append(section)

        return sections

    def compile_view(self, sections=None):
        if sections is None:
            sections = self.build_sections(self.member, self.user, self.suspicions)

        for section in sections:
            self.add_item(section)
            self.add_item(discord.ui.Separator())

        self.action_row = InsightView.ActionRow(self, self.member)
        self.add_item(self.action_row)

    @staticmethod
    def gather_suspicions(user, member):
        suspicions = Suspicions()
        if datetime.now(timezone.utc) - user.created_at < timedelta(weeks=30):
            suspicions.account_age = True
        if user.avatar is None:
            suspicions.default_avatar = True
        if re.match(r".*[0-9][0-9][0-9]$", user.name):
            suspicions.username_digits = True
        suspicions.rejoined = member.flags.did_rejoin
        suspicions.flagged_spammer = member.public_flags.spammer
        return suspicions

    def _save_view(self):
        if str(self.guild.id) not in InsightView.VIEWS:
            InsightView.VIEWS[str(self.guild.id)] = dict()
        if str(self.user.id) not in InsightView.VIEWS[str(self.guild.id)]:
            InsightView.VIEWS[str(self.guild.id)][str(self.user.id)] = list()
        InsightView.VIEWS[str(self.guild.id)][str(self.user.id)].append(self)

    class ActionRow(discord.ui.ActionRow):
        def __init__(self, view, member):
            super().__init__()
            self._view = view
            self.member = member
            if len(view.suspicions) == 0:
                self.remove_item(self.greet_button)

        @discord.ui.button(label="Greet", style=discord.ButtonStyle.green)
        @button_requires_permission(manage_messages=True)
        async def greet_button(
            self, interaction: discord.Interaction, button: discord.ui.Button
        ):
            channel = discord.utils.get(
                interaction.guild.text_channels, name="general-chat"
            )
            embed = discord.Embed(
                color=0x00FF00,
                description=f"Welcome {self.member.mention} to Zyra's Garden of Thorns.\n\nWe hope that you enjoy your stay.",
            )
            embed.set_author(
                name=self.member.display_name,
                icon_url=(
                    interaction.guild.icon.url if interaction.guild.icon else None
                ),
            )
            embed.set_thumbnail(
                url=interaction.guild.icon.url if interaction.guild.icon else None
            )
            await channel.send(embed=embed)
            await self._view.greeted()

        @discord.ui.button(label="Kick", style=discord.ButtonStyle.red)
        @button_requires_permission(kick_members=True)
        async def kick_button(
            self, interaction: discord.Interaction, button: discord.ui.Button
        ):
            await self.member.kick(reason="Suspicious account.")
            await self._view.kicked()

        @discord.ui.button(label="Ban", style=discord.ButtonStyle.red)
        @button_requires_permission(ban_members=True)
        async def ban_button(
            self, interaction: discord.Interaction, button: discord.ui.Button
        ):
            await self.member.ban(
                reason=f"Banned by insight command. Suspicions: {', '.join([suspicion[2:] for suspicion in self._view.suspicions])}"
            )
            await self._view.banned()

    async def update_view(self):
        if self.message is not None:
            await self.message.edit(view=self)

    async def greeted(self, auto=False):
        self.update_status(
            f"*✅ User has been greeted{' automatically' if auto else ''}.*"
        )
        if self.action_row is not None:
            self.action_row.remove_item(self.action_row.greet_button)
        await self.update_view()

    @classmethod
    async def user_greeted(cls, guild_id, user_id, auto=False):
        if str(user_id) in cls.VIEWS[str(guild_id)]:
            for view in cls.VIEWS[str(guild_id)][str(user_id)]:
                await view.greeted(auto=auto)

    async def kicked(self, auto=False):
        self.voluntary_leave = False
        self.update_status(
            f"*🚫 User has been kicked{' automatically' if auto else ''}.*"
        )
        if self.action_row is not None:
            self.action_row.remove_item(self.action_row.greet_button)
            self.action_row.remove_item(self.action_row.kick_button)
        await self.update_view()

    @classmethod
    async def user_kicked(cls, guild_id, user_id, auto=False):
        if str(user_id) in cls.VIEWS[str(guild_id)]:
            for view in cls.VIEWS[str(guild_id)][str(user_id)]:
                await view.kicked(auto=auto)

    async def banned(self, auto=False):
        self.voluntary_leave = False
        self.update_status(
            f"*🚫 User has been banned{' automatically' if auto else ''}.*"
        )
        if self.action_row is not None:
            self.remove_item(self.action_row)
        await self.update_view()

    @classmethod
    async def user_banned(cls, guild_id, user_id, auto=False):
        if str(user_id) in cls.VIEWS[str(guild_id)]:
            for view in cls.VIEWS[str(guild_id)][str(user_id)]:
                await view.banned(auto=auto)

    async def left(self):
        if not self.voluntary_leave:
            return
        self.update_status("*❓ User has left the server.*")
        if self.action_row is not None:
            self.action_row.remove_item(self.action_row.greet_button)
            self.action_row.remove_item(self.action_row.kick_button)
        await self.update_view()

    @classmethod
    async def user_left(cls, guild_id, user_id):
        if str(user_id) in cls.VIEWS[str(guild_id)]:
            for view in cls.VIEWS[str(guild_id)][str(user_id)]:
                await view.left()

    async def on_timeout(self):
        if self.status_section is None:
            self.update_status("*⏰ This view has timed out.*")
        if self.action_row is not None:
            self.remove_item(self.action_row)
        if self in self.VIEWS[str(self.guild.id)][str(self.user.id)]:
            self.VIEWS[str(self.guild.id)][str(self.user.id)].remove(self)
        await self.update_view()

    @classmethod
    async def do_timeout(cls):
        for guild_id in cls.VIEWS:
            for user_id in cls.VIEWS[guild_id]:
                for view in cls.VIEWS[guild_id][user_id]:
                    await view.on_timeout()

    def update_status(self, status):
        if self.status_section is not None:
            self.remove_item(self.status_section)
        self.status_section = discord.ui.TextDisplay(content=status)
        self.add_item(self.status_section)
