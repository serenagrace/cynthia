import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cynthia.bot.applications.status import about
from cynthia.utils.about import GITHUB_URL, build_about_embed


def make_client():
    return SimpleNamespace(
        app_meta=SimpleNamespace(
            version="1.6.0",
            run_timestamp="2026-10-29 12:00:00",
            git_hash="abc123",
            git_timestamp="2026-10-29 11:00:00",
        ),
        user=SimpleNamespace(
            name="CynthiaBot",
            display_avatar=SimpleNamespace(url="https://example.invalid/bot.png"),
        ),
        loaded_command_count=3,
        loaded_cog_count=2,
        tree=SimpleNamespace(loaded_modules=["one"], modules=["one", "two"]),
        discovered_cogs=["first", "second"],
    )


def test_about_embed_includes_version_link_bot_identity_and_startup_details():
    embed = build_about_embed(
        make_client(), ["load failed", "second", "third", "fourth"]
    )

    assert embed.title == "Cynthia (1.6.0)"
    assert embed.description == f"View my [GitHub]({GITHUB_URL})"
    assert embed.url is None
    assert embed.author.name == "CynthiaBot"
    assert embed.author.icon_url == "https://example.invalid/bot.png"
    assert embed.fields[0].name == "Launch Time:"
    assert embed.fields[1].name == "Loaded Commands:"
    assert embed.fields[2].name == "Loaded Cogs:"
    assert embed.fields[3].value == "-load failed\n-second\n-third\n..."
    assert embed.footer.text == "#abc123 2026-10-29 11:00:00"


def test_about_command_sends_shared_embed():
    interaction = SimpleNamespace(
        client=make_client(),
        response=SimpleNamespace(send_message=AsyncMock()),
    )

    asyncio.run(about.callback(interaction))

    sent_embed = interaction.response.send_message.await_args.kwargs["embed"]
    assert sent_embed.title == "Cynthia (1.6.0)"
    assert sent_embed.author.name == "CynthiaBot"
