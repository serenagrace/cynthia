"""Owner-only DM commands that run Twitch streams through OBS, and public /twitchurl."""

import asyncio
import logging
import time

import aiohttp
import discord
from discord import app_commands

from cynthia.utils.auth import OwnerGroup
from cynthia.utils.embeds import TWITCH, make_embed
from cynthia.utils.obs import OBSError
from cynthia.utils.obslayout import LayoutError
from cynthia.utils.streamcfg import setting
from cynthia.utils.twitchapi import TwitchAPIError
from cynthia.utils.twitchchat import clear_pane, pane_messages

logger = logging.getLogger(__name__)

TEST_TASK = "_twitch_test_task"
AUTH_TASK = "_twitch_auth_task"
BOT_AUTH_TASK = "_twitch_bot_auth_task"
# How long /twitch start waits for a Twitch approval before streaming anyway
START_AUTH_WAIT_SECONDS = 300

twitch = OwnerGroup(name="twitch", description="Stream to Twitch through OBS.")


class ChatPaneView(discord.ui.View):
    """Let the command's owner remove displayed messages without Twitch access."""

    def __init__(self, user_id, state):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.state = state
        options = [
            discord.SelectOption(
                label=f"{message['user']} · {time.strftime('%H:%M:%S', time.localtime(message['time']))}"[
                    :100
                ],
                description=message["text"][:100],
                value=message["id"],
            )
            for message in reversed(pane_messages(state))
            if message["id"]
        ]
        self.messages = discord.ui.Select(
            placeholder="Choose a message to remove",
            options=options,
            row=0,
            disabled=not options,
        )
        if not options:
            self.messages.options = [
                discord.SelectOption(label="No messages", value="-")
            ]
        self.messages.callback = self.remove_message
        self.add_item(self.messages)

    async def interaction_check(self, interaction: discord.Interaction):
        """Only the owner who opened this view may change the pane."""
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "Only whoever ran this command can use these controls.", ephemeral=True
        )
        return False

    async def remove_message(self, interaction: discord.Interaction):
        """Hide the selected message and refresh the available choices."""
        clear_pane(self.state, message_id=self.messages.values[0])
        await interaction.response.edit_message(
            content="Message removed from the pane only. Twitch chat is unchanged.",
            view=ChatPaneView(self.user_id, self.state),
        )

    @discord.ui.button(label="Clear pane", style=discord.ButtonStyle.danger, row=1)
    async def clear_all(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Hide all existing pane messages, leaving future chat visible."""
        clear_pane(self.state)
        await interaction.response.edit_message(
            content="Chat pane cleared. Twitch chat is unchanged.", view=None
        )


@twitch.command(
    name="clearchat", description="Remove chat pane messages locally, not from Twitch."
)
@app_commands.describe(user="Remove this Twitch user's existing messages instead")
async def clearchat(interaction: discord.Interaction, user: str = None):
    """Open a message picker, or clear a user's existing pane messages."""
    state = interaction.client.dman.uns
    if user is not None:
        login = user.strip().lstrip("@").lower()
        if not login:
            raise app_commands.CheckFailure("Enter a Twitch username.")
        clear_pane(state, login=login)
        await interaction.response.send_message(
            f"Removed `{login}`'s existing pane messages. Twitch chat is unchanged.",
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return
    await interaction.response.send_message(
        "Remove one message or clear the whole pane. Twitch chat is unchanged.",
        view=ChatPaneView(interaction.user.id, state),
    )


def obs_cog(interaction):
    """Return the OBS cog or explain that it isn't loaded."""
    cog = interaction.client.get_cog("OBSCog")
    if cog is None:
        raise app_commands.CheckFailure("The OBS cog isn't loaded.")
    return cog


def stream_key(interaction):
    """The Twitch key from `.env` (`TWITCH_STREAM_KEY`, else `OBS_STREAM_KEY`)."""
    env = interaction.client.env
    return env.get("TWITCH_STREAM_KEY", None) or env.get("OBS_STREAM_KEY", None)


def channel(interaction):
    """The Twitch channel name from `.env`, if set."""
    return interaction.client.env.get("TWITCH_CHANNEL", None) or None


def duration(seconds):
    """Format seconds as `1h 02m 03s`."""
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    return f"{minutes}m {secs:02d}s" if minutes else f"{secs}s"


def health_fields(status):
    """Embed fields with the health numbers of a running stream."""
    seconds = max(status["stream_seconds"], 1)
    total = max(status["total_frames"], 1)
    fields = [
        ("Uptime", duration(status["stream_seconds"])),
        ("Average bitrate", f"{status['bytes'] * 8 / seconds / 1000:.0f} kbps"),
        (
            "Skipped frames",
            f"{status['skipped_frames']} ({status['skipped_frames'] / total:.2%})",
        ),
        ("Congestion", f"{status['congestion']:.0%}"),
    ]
    if status["reconnecting"]:
        fields.append(("Connection", "Reconnecting…"))
    return fields


def approval_embed(flow, note):
    """The Twitch device-code prompt: where to go and which code to approve."""
    return make_embed(
        "🔑 Approve the bot on Twitch",
        note,
        color=TWITCH,
        url=flow["verification_uri"],
        fields=[
            ("Open", flow["verification_uri"]),
            ("Code", f"**{flow['user_code']}**"),
        ],
    )


async def begin(interaction, bandwidth_test):
    """Prepare OBS (video mode, layout, key) and start streaming."""
    cog = obs_cog(interaction)
    status = await asyncio.to_thread(cog.obs.status)
    if status["streaming"]:
        raise OBSError("OBS is already streaming; use `/twitch stop` first.")
    uns = interaction.client.dman.uns
    kbps = int(interaction.client.config.get("twitch_bitrate_kbps", 6000))
    await cog.prepare()
    await asyncio.to_thread(
        cog.obs.set_stream_key, stream_key(interaction), bandwidth_test, kbps
    )
    await asyncio.to_thread(cog.obs.start_stream)
    return f"{setting(uns, 'obs_height')}p{setting(uns, 'obs_fps')} at {kbps} kbps"


# How long the /twitch start and stop buttons wait for an answer
CONFIRM_SECONDS = 60


def health_lines(status):
    """The stream's health numbers as `**Name:** value` lines."""
    return [f"**{name}:** {value}" for name, value in health_fields(status)]


class ConfirmView(discord.ui.LayoutView):
    """Asks for a button press before running `action`, then shows its result.

    `action(interaction)` returns `(heading, lines, color)` for the final view.
    Only the user who ran the command can answer; nothing happens on Cancel or
    when the buttons time out.
    """

    def __init__(self, user_id, prompt, lines, color, label, action, unchanged):
        """Show `prompt` and `lines` with a `label` button and a Cancel button."""
        super().__init__(timeout=CONFIRM_SECONDS)
        self.user_id = user_id
        self.action = action
        self.unchanged = unchanged
        self.color = color
        self.message = None
        self.done = False
        self.buttons = discord.ui.ActionRow()
        confirm = discord.ui.Button(label=label, style=discord.ButtonStyle.danger)
        cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
        confirm.callback = self.confirm
        cancel.callback = self.cancel
        self.buttons.add_item(confirm)
        self.buttons.add_item(cancel)
        self.show(prompt, lines, color, buttons=True)

    def show(self, heading, lines=(), color=None, *, buttons=False):
        """Replace the view's contents with a heading, detail lines and buttons."""
        self.clear_items()
        items = [discord.ui.TextDisplay(heading)]
        if lines:
            items += [discord.ui.Separator(), discord.ui.TextDisplay("\n".join(lines))]
        if buttons:
            items += [discord.ui.Separator(), self.buttons]
        self.add_item(discord.ui.Container(*items, accent_colour=color or self.color))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Only whoever ran the command can press the buttons."""
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "Only whoever ran this command can use these buttons.", ephemeral=True
        )
        return False

    async def confirm(self, interaction: discord.Interaction):
        """Run the action, then show what it did."""
        self.finish()
        self.show("⏳ Working on it…")
        await interaction.response.edit_message(view=self)
        heading, lines, color = await self.action(interaction)
        self.show(heading, lines, color)
        await interaction.edit_original_response(view=self)

    async def cancel(self, interaction: discord.Interaction):
        """Leave things as they are."""
        self.finish()
        self.show(f"Cancelled; {self.unchanged}")
        await interaction.response.edit_message(view=self)

    def finish(self):
        """Stop listening for presses so the decision can only be made once."""
        self.done = True
        self.stop()

    async def on_timeout(self):
        """Drop the buttons once nobody answered in time."""
        if self.done or self.message is None:
            return
        self.show(f"⏰ No answer; {self.unchanged}")
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            pass


async def ask(interaction, prompt, lines, color, label, action, unchanged):
    """Send a ConfirmView for `action` as the reply to a deferred command."""
    view = ConfirmView(
        interaction.user.id, prompt, lines, color, label, action, unchanged
    )
    view.message = await interaction.followup.send(view=view, wait=True)


@twitch.command(name="start", description="Start streaming to Twitch.")
async def start(interaction: discord.Interaction):
    """Ask for confirmation with buttons, then start the Twitch stream."""
    await interaction.response.defer(thinking=True)
    try:
        status = await asyncio.to_thread(obs_cog(interaction).obs.status)
    except OBSError as e:
        await interaction.followup.send(f"❌ {e}")
        return
    if status["streaming"]:
        await interaction.followup.send(
            "OBS is already streaming; use `/twitch stop` first."
        )
        return
    uns = interaction.client.dman.uns
    kbps = int(interaction.client.config.get("twitch_bitrate_kbps", 6000))
    lines = [
        f"**Video mode:** {setting(uns, 'obs_height')}p{setting(uns, 'obs_fps')} "
        f"at {kbps} kbps"
    ]
    if channel(interaction):
        lines.append(f"**Channel:** {twitch_url(interaction)}")
    await ask(
        interaction,
        "**🔴 Go live on Twitch?**",
        lines,
        TWITCH,
        "Start stream",
        start_stream,
        "the stream wasn't started.",
    )


async def start_stream(interaction):
    """Get Twitch approval if it's needed, then start streaming."""
    await authorize_before_start(interaction)
    try:
        mode = await begin(interaction, bandwidth_test=False)
    except (OBSError, LayoutError) as e:
        return f"❌ {e}", [], TWITCH
    lines = [f"**Video mode:** {mode}"]
    if channel(interaction):
        lines.append(f"**Channel:** {twitch_url(interaction)}")
    return "**🔴 Streaming to Twitch**", lines, TWITCH


async def authorize_before_start(interaction):
    """Ask for Twitch approval when it's missing, waiting a while before streaming."""
    api = getattr(interaction.client, "twitch_api", None)
    if api is None or not await api.needs_authorization():
        return
    try:
        flow = await api.start_device_flow()
    except (TwitchAPIError, aiohttp.ClientError, asyncio.TimeoutError) as e:
        await interaction.followup.send(f"⚠️ Couldn't ask Twitch for approval: {e}")
        return
    minutes = START_AUTH_WAIT_SECONDS // 60
    note = (
        "The bot needs Twitch approval to set the title and category and clip "
        f"shinies. The stream starts once you approve, or in {minutes} min."
    )
    await interaction.followup.send(embed=approval_embed(flow, note))
    task = getattr(interaction.client, AUTH_TASK, None)
    if task is not None and not task.done():
        task.cancel()
    # A late approval still finishes in the background and is confirmed by DM
    task = asyncio.create_task(finish_auth(interaction, api, flow))
    setattr(interaction.client, AUTH_TASK, task)
    await asyncio.wait({task}, timeout=START_AUTH_WAIT_SECONDS)


@twitch.command(
    name="stop", description="Stop the Twitch stream (or a bandwidth test)."
)
async def stop(interaction: discord.Interaction):
    """Ask for confirmation with buttons, then stop the Twitch stream."""
    await interaction.response.defer(thinking=True)
    try:
        status = await asyncio.to_thread(obs_cog(interaction).obs.status)
    except OBSError as e:
        await interaction.followup.send(f"❌ {e}")
        return
    if not status["streaming"]:
        await interaction.followup.send("OBS isn't streaming.")
        return
    await ask(
        interaction,
        "**⏹️ Stop the Twitch stream?**",
        health_lines(status),
        TWITCH,
        "Stop stream",
        stop_stream,
        "the stream is still running.",
    )


async def stop_stream(interaction):
    """Stop the stream (and any bandwidth test) and report its final numbers."""
    cog = obs_cog(interaction)
    task = getattr(interaction.client, TEST_TASK, None)
    if task is not None and not task.done():
        task.cancel()
    try:
        status = await asyncio.to_thread(cog.obs.status)
        if not status["streaming"]:
            return "OBS had already stopped streaming.", [], TWITCH
        await asyncio.to_thread(cog.obs.stop_stream)
    except OBSError as e:
        return f"❌ {e}", [], TWITCH
    return "**⏹️ Stream stopped**", health_lines(status), TWITCH


@twitch.command(name="test", description="Run Twitch's bandwidth test through OBS.")
@app_commands.describe(minutes="How long to test before stopping automatically")
async def test(
    interaction: discord.Interaction, minutes: app_commands.Range[int, 1, 10] = 2
):
    """Stream in Twitch's bandwidth-test mode (nothing goes live), then report."""
    await interaction.response.defer(thinking=True)
    try:
        mode = await begin(interaction, bandwidth_test=True)
    except (OBSError, LayoutError) as e:
        await interaction.followup.send(f"❌ {e}")
        return
    await interaction.followup.send(
        f"📶 Bandwidth test running at {mode}. Nothing goes live. "
        f"I'll stop and report in {minutes} min (or use `/twitch stop`)."
    )
    task = asyncio.create_task(finish_test(interaction, minutes))
    setattr(interaction.client, TEST_TASK, task)


async def finish_test(interaction, minutes):
    """Wait out the test, stop streaming, and DM the numbers."""
    cog = obs_cog(interaction)
    try:
        await asyncio.sleep(minutes * 60)
        status = await asyncio.to_thread(cog.obs.status)
        await asyncio.to_thread(cog.obs.stop_stream)
        embed = make_embed(
            "📶 Bandwidth test finished", color=TWITCH, fields=health_fields(status)
        )
        await interaction.user.send(embed=embed)
    except asyncio.CancelledError:
        return
    except OBSError as e:
        await interaction.user.send(f"❌ The bandwidth test ended with an error: {e}")


def twitch_url(interaction):
    """The channel's public URL."""
    return f"https://twitch.tv/{channel(interaction)}"


async def live_state(interaction):
    """(live, fields): live is True/False, or None when it can't tell.

    Twitch itself is asked when the bot is authorized, since only it knows a
    bandwidth test isn't live, and it also gives the title, game and viewers.
    Otherwise OBS's stream state is used.
    """
    api = getattr(interaction.client, "twitch_api", None)
    if api is not None and api.authorized:
        try:
            stream = await api.live_stream(channel(interaction))
        except (TwitchAPIError, aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.debug("Couldn't ask Twitch whether the stream is live: %s", e)
        else:
            if stream is None:
                return False, []
            fields = [
                ("Title", stream.get("title"), False),
                ("Category", stream.get("game_name")),
                ("Viewers", stream.get("viewer_count")),
            ]
            return True, [f for f in fields if f[1] not in (None, "")]
    cog = interaction.client.get_cog("OBSCog")
    if cog is None:
        return None, []
    try:
        status = await asyncio.to_thread(cog.obs.status)
    except OBSError:
        return None, []
    test = getattr(interaction.client, TEST_TASK, None)
    if not status["streaming"] or (test is not None and not test.done()):
        return False, []
    return True, [("Uptime", duration(status["stream_seconds"]))]


@app_commands.command(
    name="twitchurl", description="Show the Twitch channel and whether it's live."
)
async def twitchurl(interaction: discord.Interaction):
    """Show the channel URL and whether the channel is live right now."""
    if not channel(interaction):
        await interaction.response.send_message(
            "This bot has no Twitch channel set.", ephemeral=True
        )
        return
    await interaction.response.defer(thinking=True)
    live, fields = await live_state(interaction)
    state = {True: "🔴 **Live now**", False: "⚫ Offline right now"}.get(
        live, "Couldn't check whether the channel is live."
    )
    link = twitch_url(interaction)
    embed = make_embed(
        f"{channel(interaction)} on Twitch",
        f"{state}\n{link}",
        color=TWITCH,
        url=link,
        fields=fields,
    )
    await interaction.followup.send(embed=embed)


@twitch.command(
    name="auth", description="Let the bot set the title and category and clip shinies."
)
async def auth(interaction: discord.Interaction):
    """Authorize the bot on Twitch with a device code."""
    await authorize(interaction)


@twitch.command(
    name="botauth", description="Authorize a separate Twitch bot account for chat."
)
async def botauth(interaction: discord.Interaction):
    """Keep the bot's chat authorization separate from the broadcaster's."""
    await authorize(interaction, chat=True)


async def authorize(interaction, chat=False):
    api = getattr(interaction.client, "twitch_chat_api" if chat else "twitch_api", None)
    if api is None:
        await interaction.response.send_message(
            "Set `TWITCH_CLIENT_ID` in `.env` and restart first.", ephemeral=True
        )
        return
    await interaction.response.defer(thinking=True)
    try:
        flow = await api.start_device_flow()
    except (TwitchAPIError, aiohttp.ClientError, asyncio.TimeoutError) as e:
        await interaction.followup.send(f"❌ {e}")
        return
    note = "I'll confirm here once Twitch accepts it."
    if chat:
        note += (
            "\nOpen the approval link in a private browser window and sign in as "
            "the **bot account**, not your broadcaster account. "
            "This won't replace your broadcaster authorization."
        )
    await interaction.followup.send(embed=approval_embed(flow, note))
    task_key = BOT_AUTH_TASK if chat else AUTH_TASK
    task = getattr(interaction.client, task_key, None)
    if task is not None and not task.done():
        task.cancel()
    task = asyncio.create_task(finish_auth(interaction, api, flow))
    setattr(interaction.client, task_key, task)


async def finish_auth(interaction, api, flow):
    """Wait for the owner to approve the code, then report the result."""
    try:
        login = await api.finish_device_flow(flow)
        role = "Chat bot" if api.auth_command == "/twitch botauth" else "Broadcaster"
        message = f"✅ {role} authorized for **{login}**."
    except asyncio.CancelledError:
        return
    except (TwitchAPIError, aiohttp.ClientError, asyncio.TimeoutError) as e:
        message = f"❌ {e}"
    await interaction.user.send(message)


@twitch.command(name="uptime", description="Show how long the stream has been live.")
async def uptime(interaction: discord.Interaction):
    """Show the stream's uptime."""
    await interaction.response.defer(thinking=True)
    try:
        status = await asyncio.to_thread(obs_cog(interaction).obs.status)
    except OBSError as e:
        await interaction.followup.send(f"❌ {e}")
        return
    if not status["streaming"]:
        await interaction.followup.send("OBS isn't streaming.")
        return
    await interaction.followup.send(f"Live for {duration(status['stream_seconds'])}.")


@twitch.command(name="status", description="Show stream health and the video mode.")
async def status(interaction: discord.Interaction):
    """Show OBS output health."""
    await interaction.response.defer(thinking=True)
    try:
        info = await asyncio.to_thread(obs_cog(interaction).obs.status)
    except OBSError as e:
        await interaction.followup.send(f"❌ {e}")
        return
    await interaction.followup.send(embed=status_embed(interaction, info))


def status_embed(interaction, info):
    """OBS's streaming and recording state, with stream health when live."""
    uns = interaction.client.dman.uns
    mode = f"{setting(uns, 'obs_height')}p{setting(uns, 'obs_fps')}"
    fields = [("Video mode", mode)]
    if info["streaming"]:
        title = "🔴 Live"
        fields += health_fields(info)
    else:
        title = "⚫ Not streaming"
    if info["recording"]:
        fields.append(("⏺️ Recording", duration(info["record_seconds"])))
    return make_embed(title, color=TWITCH, fields=fields)


# /twitch is owner-only and DM-only; /twitchurl is open to everyone
__application__ = [twitch, twitchurl]
