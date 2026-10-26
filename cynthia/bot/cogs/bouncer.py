import discord
from discord.ext import commands
from cynthia.views import InsightView
import logging

_logger = logging.getLogger(__name__)
_logger.setLevel(logging.DEBUG)


class BouncerCog(commands.Cog):

    GREETINGS = dict()

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
        if not len(suspicions):
            greet_channel = discord.utils.get(guild.text_channels, name="general-chat")
            if greet_channel:
                embed = discord.Embed(
                    color=0x00FF00,
                    description=f"Welcome {member.mention} to Zyra's Garden of Thorns.\n\nWe hope that you enjoy your stay.",
                )
                embed.set_author(
                    name=member.display_name,
                    icon_url=guild.icon.url if guild.icon else None,
                )
                embed.set_thumbnail(url=guild.icon.url if guild.icon else None)

                if str(guild.id) not in BouncerCog.GREETINGS:
                    BouncerCog.GREETINGS[str(guild.id)] = dict()

                BouncerCog.GREETINGS[str(guild.id)][str(user.id)] = (
                    await greet_channel.send(embed=embed)
                )

                await InsightView.user_greeted(guild.id, member.id, auto=True)

        to_ban = (
            suspicions.flagged_spammer
            or sum(
                1
                for suspicion in ["account_age", "username_digits", "default_avatar"]
                if getattr(suspicions, suspicion)
            )
            >= 2
        ) and not suspicions.rejoined
        to_kick = suspicions.username_digits and not suspicions.rejoined

        if to_ban:
            await InsightView.user_banned(guild.id, member.id, auto=True)
            await member.ban(
                reason=f"Auto-Banned by bouncer. Suspicions: {', '.join([suspicion[2:] for suspicion in suspicions])}"
            )
        elif to_kick:
            await InsightView.user_kicked(guild.id, member.id, auto=True)
            await member.kick(
                reason=f"Auto-Kicked by bouncer. Suspicions: {', '.join([suspicion[2:] for suspicion in suspicions])}"
            )
        if channel:
            view.message = await channel.send(view=view)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        guild = member.guild
        _logger.info(f"Member {member} left {guild.name}.")
        await InsightView.user_left(guild.id, member.id)
        greeting = BouncerCog.GREETINGS.get(str(guild.id), {}).pop(str(member.id), None)
        if greeting:
            await greeting.delete()

    async def cog_unload(self):
        await InsightView.do_timeout()


async def setup(bot):
    await bot.add_cog(BouncerCog(bot))
