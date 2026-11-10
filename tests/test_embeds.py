import pytest

from cynthia.utils.embeds import ERROR, error_embed


def test_error_embed_formats_a_message_with_a_contextual_title():
    embed = error_embed("USB disconnected.", title="CYNX Controller Error")
    assert embed.title == "CYNX Controller Error"
    assert embed.description == "USB disconnected."
    assert embed.color.value == ERROR
    assert not embed.fields


def test_error_embed_describes_an_exception_without_a_traceback():
    try:
        raise ValueError("Invalid controller input.")
    except ValueError as error:
        embed = error_embed(error)
    assert embed.description == "Invalid controller input."
    assert [(field.name, field.value) for field in embed.fields] == [
        ("Exception", "ValueError")
    ]


@pytest.mark.parametrize("message", ["", "   "])
def test_error_embed_keeps_blank_errors_readable(message):
    assert (
        error_embed(message).description == "No additional error details were provided."
    )


def test_error_embed_fits_discord_limits_for_long_messages_and_titles():
    embed = error_embed("x" * 5000, title="t" * 300)
    assert len(embed.title) == 256
    assert len(embed.description) == 4096
    assert embed.description.endswith("...")
