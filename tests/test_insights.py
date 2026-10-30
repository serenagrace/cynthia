import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cynthia.bot.cogs.bouncer import BouncerCog
from cynthia.views.insight import InsightView


def make_member(user, *, guild_id=20, roles=None, rejoined=False, spammer=False):
    guild = SimpleNamespace(
        id=guild_id,
        name="Test Guild",
        icon=None,
        me=SimpleNamespace(roles=[SimpleNamespace(name="Bouncer")]),
        text_channels=[],
    )
    member = SimpleNamespace(
        id=user.id,
        mention=user.mention,
        display_name=user.name,
        display_avatar=SimpleNamespace(url="https://example.invalid/avatar.png"),
        joined_at=datetime.now(timezone.utc),
        roles=roles or [],
        guild=guild,
        flags=SimpleNamespace(did_rejoin=rejoined),
        public_flags=SimpleNamespace(spammer=spammer),
        ban=AsyncMock(),
        kick=AsyncMock(),
    )
    return member


def make_user(
    *,
    user_id=42,
    name="ordinary-user",
    created_at=None,
    avatar=True,
):
    return SimpleNamespace(
        id=user_id,
        name=name,
        mention=f"<@{user_id}>",
        created_at=created_at or datetime.now(timezone.utc) - timedelta(days=365),
        avatar=object() if avatar else None,
    )


def text_contents(component):
    content = getattr(component, "content", None)
    if content is not None:
        yield content
    for child in getattr(component, "children", ()):
        yield from text_contents(child)


def test_insight_flags_suspicious_user_attributes():
    user = make_user(
        name="NewUser1234",
        created_at=datetime.now(timezone.utc) - timedelta(days=10),
        avatar=None,
    )
    member = make_member(user, spammer=True)

    suspicions = InsightView.gather_suspicions(user, member)

    assert suspicions.account_age
    assert suspicions.default_avatar
    assert suspicions.username_digits
    assert suspicions.flagged_spammer
    assert len(suspicions) == 4
    assert len(list(suspicions)) == 4


def test_insight_ignores_old_rejoined_user_flags():
    user = make_user(
        name="NewUser1234",
        created_at=datetime.now(timezone.utc) - timedelta(days=365),
        avatar=None,
    )
    member = make_member(user, rejoined=True)

    suspicions = InsightView.gather_suspicions(user, member)

    assert suspicions.default_avatar
    assert suspicions.username_digits
    assert not suspicions.account_age
    assert suspicions._nspace_dict["rejoined"]


def test_insight_view_renders_analysis_and_tracks_lifecycle():
    async def run():
        InsightView.VIEWS.clear()
        user = make_user(name="ordinary-user")
        role = SimpleNamespace(name="Moderator")
        member = make_member(user, roles=[role])
        view = InsightView(user, member)
        view.message = SimpleNamespace(edit=AsyncMock())

        contents = [text for child in view.children for text in text_contents(child)]
        assert "**User Insight:** <@42>" in contents
        assert "**Roles:** Moderator" in contents
        assert "✅ No suspicious activity detected." in contents
        assert "42" in "\n".join(contents)

        await view.kicked()
        assert not view.voluntary_leave
        assert view.status_section.content == "*🚫 User has been kicked.*"
        view.message.edit.assert_awaited_once_with(view=view)

        await view.left()
        assert view.status_section.content == "*🚫 User has been kicked.*"

        await view.on_timeout()
        assert view not in InsightView.VIEWS["20"]["42"]
        InsightView.VIEWS.clear()

    asyncio.run(run())


def test_insight_event_updates_every_open_view():
    async def run():
        InsightView.VIEWS.clear()
        user = make_user()
        first = InsightView(user, make_member(user))
        second = InsightView(user, make_member(user))

        await InsightView.user_greeted(20, user.id, auto=True)

        assert (
            first.status_section.content == "*✅ User has been greeted automatically.*"
        )
        assert second.status_section.content == first.status_section.content
        InsightView.VIEWS.clear()

    asyncio.run(run())


def test_insight_ban_button_keeps_view_state_after_removing_action_row():
    async def run():
        InsightView.VIEWS.clear()
        user = make_user(
            name="Suspicious1234",
            created_at=datetime.now(timezone.utc) - timedelta(days=5),
            avatar=None,
        )
        member = make_member(user)
        view = InsightView(user, member)
        events = []
        view.message = SimpleNamespace(
            edit=AsyncMock(side_effect=lambda **_: events.append("view update"))
        )
        member.ban = AsyncMock(side_effect=lambda **_: events.append("ban"))
        interaction = SimpleNamespace()
        button = view.action_row.ban_button
        callback = button.callback.callback.__wrapped__

        await callback(view.action_row, interaction, button)

        assert events == ["view update", "ban"]
        member.ban.assert_awaited_once()
        reason = member.ban.await_args.kwargs["reason"]
        assert reason.startswith("Banned by insight command. Suspicions:")
        assert "Account is less than 6 months old." in reason
        assert "Default Avatar." in reason
        assert view.action_row.view is None
        InsightView.VIEWS.clear()

    asyncio.run(run())


def test_bouncer_simulation_auto_bans_suspicious_user():
    async def run():
        InsightView.VIEWS.clear()
        user = make_user(
            name="Suspicious1234",
            created_at=datetime.now(timezone.utc) - timedelta(days=5),
            avatar=None,
        )
        member = make_member(user)
        member.guild.fetch_member = AsyncMock(return_value=member)
        user_insights = SimpleNamespace(name="user-insights", send=AsyncMock())
        general_chat = SimpleNamespace(name="general-chat", send=AsyncMock())
        member.guild.text_channels = [user_insights, general_chat]
        bot = SimpleNamespace(fetch_user=AsyncMock(return_value=user))

        await BouncerCog(bot).on_member_join(member)

        member.ban.assert_awaited_once()
        member.kick.assert_not_awaited()
        user_insights.send.assert_awaited_once()
        assert "Auto-Banned by bouncer" in member.ban.await_args.kwargs["reason"]
        InsightView.VIEWS.clear()

    asyncio.run(run())
