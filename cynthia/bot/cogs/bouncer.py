import discord
from discord.ext import commands
from datetime import datetime, timezone, timedelta
from cynthia.utils.auth import button_requires_permission
import re
import logging

_logger = logging.getLogger(__name__)
_logger.setLevel(logging.DEBUG)


class InsightView(discord.ui.LayoutView):
    def __init__(self, user, member):
        super().__init__(timeout=None)
        suspicions = list()
        if datetime.now(timezone.utc) - user.created_at < timedelta(weeks=30):
            suspicions.append("⚠️ Account is less than 6 months old.")
        if user.avatar is None:
            suspicions.append("⚠️ Default Avatar.")
        if re.match(r".*[0-9][0-9][0-9]$", user.name):
            suspicions.append("⚠️ Username ends with a string of digits.")
        if member.flags.did_rejoin:
            suspicions.append("⚠️ User has rejoined the server.")
        self.add_item(
            discord.ui.Section(
                user.mention,
                f"**Created:** {discord.utils.format_dt(user.created_at, style='R')}",
                f"**Joined:** {discord.utils.format_dt(member.joined_at, style='R')}",
                accessory=discord.ui.Thumbnail(member.display_avatar.url),
            )
        )
        self.add_item(discord.ui.Separator())
        roles = [
            role.name
            for role in sorted(member.roles, reverse=True)
            if role.name != "@everyone" and role.name != "Default"
        ]
        if len(roles) == 0:
            roles_display = "None"
        elif len(roles) <= 3:
            roles_display = ", ".join(roles)
        else:
            roles_display = ", ".join(roles[:3]) + f", and {len(roles) - 3} more"

        if len(roles):
            self.add_item(discord.ui.TextDisplay(content=f"**Roles:** {roles_display}"))
        self.add_item(discord.ui.TextDisplay(content=f"**User ID:** {user.id}"))
        self.add_item(discord.ui.Separator())
        for suspicion in suspicions:
            self.add_item(discord.ui.TextDisplay(content=suspicion))
        if len(suspicions) == 0:
            self.add_item(
                discord.ui.TextDisplay(content="✅ No suspicious activity detected.")
            )

        self.add_item(discord.ui.Separator())
        self.suspicions = suspicions
        self.member = member
        self.action_row = self.ActionRow(self, member)
        self.add_item(self.action_row)

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
            self._view.remove_item(self)
            self._view.add_item(
                discord.ui.TextDisplay(content="*✅ User has been greeted.*")
            )
            await interaction.response.edit_message(view=self._view)

        @discord.ui.button(label="Kick", style=discord.ButtonStyle.red)
        @button_requires_permission(kick_members=True)
        async def kick_button(
            self, interaction: discord.Interaction, button: discord.ui.Button
        ):
            await self.member.kick(reason="Suspicious account.")
            self._view.remove_item(self)
            self._view.add_item(
                discord.ui.TextDisplay(content="*🚫 User has been kicked.*")
            )
            await interaction.response.edit_message(view=self._view)

        @discord.ui.button(label="Ban", style=discord.ButtonStyle.red)
        @button_requires_permission(ban_members=True)
        async def ban_button(
            self, interaction: discord.Interaction, button: discord.ui.Button
        ):
            await self.member.ban(
                reason=f"Banned by insight command. Suspicions: {', '.join([suspicion[2:] for suspicion in self._view.suspicions])}"
            )
            self._view.remove_item(self)
            self._view.add_item(
                discord.ui.TextDisplay(content="*🚫 User has been banned.*")
            )
            await interaction.response.edit_message(view=self._view)


class BouncerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member):
        # Check if I have "Bouncer" Role
        guild = member.guild
        if not discord.utils.get(guild.me.roles, name="Bouncer"):
            _logger.debug(f"Bot does not have 'Bouncer' role in {guild.name}.")
            return
        _logger.info(f"Member {member} joined {guild.name}.")
        channel = discord.utils.get(guild.text_channels, name="user-insights")
        userid = str(member.id)

        user = await self.bot.fetch_user(int(userid))
        member = await guild.fetch_member(int(userid))

        view = InsightView(user, member)
        suspicions = view.suspicions
        if channel:
            await channel.send(view=view)
        if not len(suspicions):
            channel = discord.utils.get(guild.text_channels, name="general-chat")
            if channel:
                embed = discord.Embed(
                    color=0x00FF00,
                    description=f"Welcome {member.mention} to Zyra's Garden of Thorns.\n\nWe hope that you enjoy your stay.",
                )
                embed.set_author(
                    name=member.display_name,
                    icon_url=guild.icon.url if guild.icon else None,
                )
                embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
                await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        pass


async def setup(bot):
    await bot.add_cog(BouncerCog(bot))
