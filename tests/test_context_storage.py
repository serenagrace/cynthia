import asyncio
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

from cynthia.context import Context
from cynthia.context.env import EnvLoader
from cynthia.utils.db import DB_PATH, Database
from cynthia.utils.drive import Drive
from cynthia.utils.onmessage import OnMessage


def test_context_uses_isolated_config_permissions_and_env_files(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    perms_path = tmp_path / "perms.yaml"
    env_path = tmp_path / ".env"
    config_path.write_text("owner: '123'\nsilent: true\n")
    perms_path.write_text("{}\n")
    env_path.write_text("DISCORD_BOT_TOKEN=file-token\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
    monkeypatch.setattr(
        "cynthia.context.context.get_app_info",
        lambda: {
            "git_hash": "test",
            "git_timestamp": "test",
            "run_timestamp": "test",
        },
    )

    context = Context(
        SimpleNamespace(
            config=str(config_path),
            perms=str(perms_path),
            hunt="Uxie",
        )
    )

    assert context.config.owner == "123"
    assert context.config.silent is True
    assert context.config.debug is False
    assert context.args.hunt == "Uxie"
    assert context.env.DISCORD_BOT_TOKEN == "test-token"

    context.config.silent = False
    context.perms["global"] = {"owners": ["+u:123"]}
    context.update_config(context.config.dict(), context.perms.dict())

    assert "silent: false" in config_path.read_text()
    assert "global:" in perms_path.read_text()


def test_drive_path_env_overrides_config(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    perms_path = tmp_path / "perms.yaml"
    config_path.write_text("owner: '123'\ndrive_path: /from/config\n")
    perms_path.write_text("{}\n")
    (tmp_path / ".env").write_text("")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DRIVE_PATH", raising=False)
    monkeypatch.setattr(
        "cynthia.context.context.get_app_info",
        lambda: {"git_hash": "t", "git_timestamp": "t", "run_timestamp": "t"},
    )
    args = SimpleNamespace(config=str(config_path), perms=str(perms_path), hunt=None)

    assert Context(args).drive_path == "/from/config"

    monkeypatch.setenv("DRIVE_PATH", "/from/env")
    context = Context(args)
    assert context.drive_path == "/from/env"
    assert context.config.drive_path == "/from/config"


def test_uvc_resets_usb_only_when_id_is_configured(monkeypatch):
    from unittest.mock import AsyncMock

    from cynthia.daemons import uvc

    run = Mock()
    monkeypatch.setattr(uvc.subprocess, "run", run)
    monkeypatch.setattr(uvc.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(uvc.cv2, "VideoCapture", Mock())
    monkeypatch.setattr(uvc.UVC, "read_frame", AsyncMock())

    for usb_id, expected in (("0fd9:009b", 1), (None, 0)):
        run.reset_mock()
        asyncio.run(uvc.UVC(usb_id).setup())
        assert run.call_count == expected
        if expected:
            run.assert_called_once_with(["usbreset", usb_id])


def test_env_loader_file_values_are_overridden_by_process_environment(
    tmp_path, monkeypatch
):
    env_path = tmp_path / ".env"
    env_path.write_text("CYNTHIA_TEST_SETTING=file\n")
    monkeypatch.setenv("CYNTHIA_TEST_SETTING", "process")

    assert EnvLoader(env_path)()["CYNTHIA_TEST_SETTING"] == "process"


def test_database_uses_drive_path_and_persists_onmessage(tmp_path):
    drive = Drive(tmp_path)
    database = Database(drive)
    guild = SimpleNamespace(id=20, name="Test Guild")
    channel = SimpleNamespace(id=30, name="test-channel")
    unit = OnMessage(channel=channel, guild=guild)

    database.insert_onmessage(unit)
    database.insert_onmessage(unit)

    assert database.database_connected
    assert database.get_onmessage() == [("log", 20, 30, "default", "default")]
    assert (tmp_path / DB_PATH).is_file()
    with sqlite3.connect(tmp_path / DB_PATH) as connection:
        rows = connection.execute("SELECT COUNT(*) FROM onmessage").fetchone()[0]
    assert rows == 1


def test_database_disables_storage_without_drive():
    database = Database(Drive(None))

    assert not database.database_connected
    assert database.get_onmessage() == []


def test_onmessage_filters_channel_and_dispatches_matching_message():
    guild = SimpleNamespace(id=20)
    channel = SimpleNamespace(id=30)
    other_channel = SimpleNamespace(id=31)
    logger = Mock()
    unit = OnMessage(logger=logger, channel=channel, guild=guild)
    message = SimpleNamespace(channel=channel, guild=guild)
    other_message = SimpleNamespace(channel=other_channel, guild=guild)

    assert asyncio.run(unit.call(SimpleNamespace(), other_message)) is False
    logger.log_message.assert_not_called()
    assert asyncio.run(unit.call(SimpleNamespace(), message)) is True
    logger.log_message.assert_called_once_with(message)
