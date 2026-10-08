import discord
from discord import app_commands
from cynthia.utils.auth import nonglobal_command, is_owner
from cynthia.views import InsightView


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
    await interaction.followup.send(view=InsightView(user, member))


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
