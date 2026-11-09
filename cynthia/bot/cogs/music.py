"""Leave music voice channels when nobody is listening or playback stays idle."""

import logging

from discord.ext import commands, tasks

from cynthia.utils.music import get_manager

logger = logging.getLogger(__name__)

IDLE_SECONDS = 30 * 60


class MusicCog(commands.Cog):
    """Watch music connections for empty channels and inactive playback."""

    def __init__(self, bot):
        """Share the command handlers' music manager."""
        self.bot = bot
        self.manager = get_manager(bot)

    async def cog_load(self):
        """Start checking idle voice connections."""
        self.check.start()

    async def cog_unload(self):
        """Stop checking voice connections."""
        self.check.cancel()

    async def check_player(self, player):
        """Disconnect an unattended or idle player and clear its queue."""
        voice = player.voice
        if voice is None or not voice.is_connected():
            player.stop()
            self.manager.drop(player.guild)
            return
        empty = not any(not member.bot for member in voice.channel.members)
        idle = (
            player.idle_since is not None
            and player.loop.time() - player.idle_since >= IDLE_SECONDS
            and not voice.is_playing()
        )
        if empty or idle:
            await player.disconnect()
            self.manager.drop(player.guild)
            logger.info(
                "Left music voice channel in guild %s: %s.",
                player.guild.id,
                "no listeners" if empty else "idle for 30 minutes",
            )

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Leave immediately when the last listener leaves the music channel."""
        player = self.manager.players.get(member.guild.id)
        if player is None:
            return
        voice = player.voice
        if voice is None or voice.channel in (before.channel, after.channel):
            await self.check_player(player)

    @tasks.loop(seconds=15)
    async def check(self):
        """Check timeouts and recover from missed voice-state events."""
        for player in list(self.manager.players.values()):
            try:
                await self.check_player(player)
            except Exception:
                logger.exception(
                    "Couldn't clean up music voice in guild %s.", player.guild.id
                )

    @check.before_loop
    async def before_check(self):
        """Wait for Discord's voice-channel member cache."""
        await self.bot.wait_until_ready()


async def setup(bot):
    """Register music voice cleanup."""
    await bot.add_cog(MusicCog(bot))
