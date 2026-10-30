"""Send owner alerts, interaction lists, and message-triggered responses."""

import discord

from .response_matrix import ResponseMatrix


class Messenger:
    """Wrap Discord message delivery and configured keyword responses."""

    def __init__(self, bot_obj):
        """Store the bot client used for message delivery."""
        self.bot = bot_obj

    async def msg_owner(self, msg, *, embed=None, file=None, silent=False, alert=False):
        """Send a message or embed to the configured bot owner."""
        user_owner = await self.bot.fetch_user(self.bot.config.owner)
        await self.send_msg(
            user_owner, msg, embed=embed, file=file, silent=silent, alert=alert
        )

    async def send_msg(
        self, send_context, msg, *, embed=None, file=None, silent=False, alert=False
    ):
        """Send content with configured silent and alert behavior."""
        if isinstance(msg, discord.Embed):
            await send_context.send(
                embed=msg, silent=(self.bot.config.silent or silent) and not alert
            )
        else:
            await send_context.send(
                msg, embed=embed, file=file, silent=self.bot.config.silent and silent
            )

    async def send_list(self, send_context, title, items):
        """Send a titled list of items through an interaction response."""
        if not items:
            await send_context.response.send_message(f"{title}\n*(Empty.)*")
            return

        formatted_items = "\n".join(f" - {item}" for item in items)
        await send_context.response.send_message(f"{title}\n{formatted_items}")

    async def respond(self, message):
        """Run a response-matrix handler for a matching message."""
        # don't respond to ourselves
        if message.author == self.bot.user:
            return

        if message.content in ResponseMatrix:
            await ResponseMatrix[message.content](self, message)
