import discord
from datetime import datetime, timezone, timedelta
from discord import app_commands
from cynthia.utils.auth import nonglobal_command, is_owner
import re


@app_commands.command()
@app_commands.default_permissions(administrator=True)
@is_owner()
@nonglobal_command()
async def verify(interaction: discord.Interaction, code: app_commands.Range[str, 6, 6]):
    await interaction.response.send_message(
        interaction.client.verify(code), ephemeral=True
    )


@app_commands.command()
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
async def insight(interaction: discord.Interaction, userid: str):
    user = await interaction.client.fetch_user(int(userid))
    member = await interaction.guild.fetch_member(int(userid))
    if member is None:
        await interaction.response.send_message(
            f"Member with ID {userid} not found.", ephemeral=True
        )
        return
    await interaction.response.defer(thinking=True)

    def insight_view(user, member) -> discord.ui.LayoutView:
        suspicions = list()
        if datetime.now(timezone.utc) - user.created_at < timedelta(weeks=30):
            suspicions.append("⚠️ Account is less than 6 months old.")
        if user.avatar is None:
            suspicions.append("⚠️ Default Avatar.")
        if re.match(r".*[0-9][0-9][0-9]$", user.name):
            suspicions.append("⚠️ Username ends with a string of digits.")
        if member.flags.did_rejoin:
            suspicions.append("⚠️ User has rejoined the server.")
        view = discord.ui.LayoutView(timeout=None)
        view.add_item(
            discord.ui.Section(
                user.mention,
                str(user.id),
                accessory=discord.ui.Thumbnail(member.display_avatar.url),
            )
        )
        view.add_item(discord.ui.Separator())
        view.add_item(
            discord.ui.TextDisplay(
                content=f"**Created:** {discord.utils.format_dt(user.created_at, style='R')}"
            )
        )
        view.add_item(
            discord.ui.TextDisplay(
                content=f"**Joined:** {discord.utils.format_dt(member.joined_at, style='R')}"
            )
        )
        roles = [
            role.name
            for role in sorted(member.roles, reverse=True)
            if role.name != "@everyone"
        ]
        if len(roles) == 0:
            roles_display = "None"
        elif len(roles) <= 3:
            roles_display = ", ".join(roles)
        else:
            roles_display = ", ".join(roles[:3]) + f", and {len(roles) - 3} more"

        view.add_item(discord.ui.TextDisplay(content=f"**Roles:** {roles_display}"))
        view.add_item(discord.ui.Separator())
        for suspicion in suspicions:
            view.add_item(discord.ui.TextDisplay(content=suspicion))
        if len(suspicions) == 0:
            view.add_item(
                discord.ui.TextDisplay(content="✅ No suspicious activity detected.")
            )

        view.add_item(discord.ui.Separator())
        kick_button = discord.ui.Button(label="Kick", style=discord.ButtonStyle.danger)

        async def kick_callback(interaction: discord.Interaction):
            await member.kick(reason="Suspicious account.")
            await interaction.response.send_message(
                f"{member} has been kicked.", ephemeral=True
            )

        kick_button.callback = kick_callback
        ban_button = discord.ui.Button(label="Ban", style=discord.ButtonStyle.danger)

        async def ban_callback(interaction: discord.Interaction):
            await member.ban(
                reason=f"Banned by insight command. Suspicions: {', '.join([suspicion[2:] for suspicion in suspicions])}"
            )
            await interaction.response.send_message(
                f"{member} has been banned.", ephemeral=True
            )

        ban_button.callback = ban_callback
        view.add_item(discord.ui.ActionRow(kick_button, ban_button))
        return view

    await interaction.followup.send(view=insight_view(user, member), ephemeral=True)


@app_commands.command()
@app_commands.guild_only()
@app_commands.default_permissions(manage_messages=True)
async def greet(interaction: discord.Interaction, userid: str):
    member = await interaction.guild.fetch_member(int(userid))
    channel = discord.utils.get(interaction.guild.text_channels, name="general-chat")
    if member is None:
        await interaction.response.send_message(
            f"Member with ID {userid} not found.", ephemeral=True
        )
        return
    await interaction.response.defer(thinking=True)

    embed = discord.Embed(
        color=0x00FF00,
        description=f"Welcome {member.mention} to Zyra's Garden of Thorns.\n\nWe hope that you enjoy your stay.",
    )
    embed.set_author(
        name=member.display_name,
        icon_url=interaction.guild.icon.url if interaction.guild.icon else None,
    )
    embed.set_thumbnail(
        url=interaction.guild.icon.url if interaction.guild.icon else None
    )

    if channel:
        await channel.send(embed=embed)
        await interaction.followup.send("Greeting sent successfully.", ephemeral=True)
    else:
        await interaction.followup.send(embed=embed)


@app_commands.command()
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
async def test_join(interaction: discord.Interaction, userid: str):
    member = interaction.guild.get_member(int(userid))
    if member is None:
        try:
            member = await interaction.guild.fetch_member(int(userid))
        except discord.NotFound:
            await interaction.response.send_message(
                f"Member with ID {userid} not found.", ephemeral=True
            )
            return
    await interaction.response.send_message(
        f"Simulating join for {member.mention}...", ephemeral=True
    )
    interaction.client.dispatch("member_join", member)


__application__ = [insight, greet, test_join]
