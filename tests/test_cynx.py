"""Exercise CyNX framing, discovery, acknowledgments, and transport recovery."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cynthia.utils.cynx import (
    CyNXClient,
    CyNXError,
    CyNXRejected,
    CyNXStopped,
    CyNXUnavailable,
    discover,
    read_frame,
    write_frame,
)


class FakePi:
    """A bounded two-port peer that records actual step executions."""

    def __init__(self, *, drop_completed=False, bad_event=None, passphrase="test"):
        self.drop_completed = drop_completed
        self.bad_event = bad_event
        self.passphrase = passphrase
        self.session = "session-one"
        self.completed = 0
        self.executions = []
        self.writers = set()
        self.tasks = set()
        self.servers = []
        self.reject_connect = False
        self.expired_session = False
        self.completion_gate = None

    async def __aenter__(self):
        self.servers = [
            await asyncio.start_server(self.command, "127.0.0.1", 0),
            await asyncio.start_server(self.macro, "127.0.0.1", 0),
        ]
        self.command_port, self.macro_port = [
            server.sockets[0].getsockname()[1] for server in self.servers
        ]
        return self

    async def __aexit__(self, *args):
        for server in self.servers:
            server.close()
            await server.wait_closed()
        for writer in list(self.writers):
            writer.close()
        if self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)

    def status(self):
        return {
            "identity": "cynx",
            "protocol": 1,
            "session": self.session,
            "boot_id": "boot-one",
            "version": "0.0.0",
            "macro_port": self.macro_port,
            "command_port": self.command_port,
            "last_completed_id": self.completed,
            "reconnect_grace": 0.3,
            "heartbeat_timeout": 0.1,
            "recovery_timeout": 0.1,
            "switch_connected": True,
            "spoofing": True,
        }

    async def command(self, reader, writer):
        self.tasks.add(asyncio.current_task())
        self.writers.add(writer)
        try:
            while line := await reader.readline():
                frame = json.loads(line)
                if (
                    frame["command"] == "hello"
                    and frame.get("passphrase") != self.passphrase
                ):
                    response = {
                        "id": frame["id"],
                        "ok": False,
                        "code": "unauthorized",
                        "error": "Authentication failed.",
                    }
                elif frame["command"] == "status" and self.expired_session:
                    response = {
                        "id": frame["id"],
                        "ok": False,
                        "code": "session_expired",
                        "error": "Session expired.",
                        "result": {"last_completed_id": self.completed},
                    }
                elif frame["command"] == "connect" and self.reject_connect:
                    response = {
                        "id": frame["id"],
                        "ok": False,
                        "code": "usb_unavailable",
                        "error": "Switch is not awake.",
                    }
                else:
                    response = {"id": frame["id"], "ok": True, "result": self.status()}
                await write_frame(writer, response)
        finally:
            self.writers.discard(writer)
            self.tasks.discard(asyncio.current_task())
            writer.close()
            await writer.wait_closed()

    async def macro(self, reader, writer):
        self.tasks.add(asyncio.current_task())
        self.writers.add(writer)
        try:
            attach = json.loads(await reader.readline())
            await write_frame(
                writer,
                {"id": attach["id"], "ok": True, "result": self.status()},
            )
            while line := await reader.readline():
                frame = json.loads(line)
                step_id = frame["id"]
                response = {"id": step_id, "session": self.session, "ok": True}
                if self.bad_event:
                    await write_frame(writer, {**response, **self.bad_event})
                    continue
                await write_frame(writer, {**response, "event": "accepted"})
                if step_id > self.completed:
                    self.executions.append(frame["step"])
                    if self.completion_gate is not None:
                        await self.completion_gate.wait()
                    self.completed = step_id
                if self.drop_completed:
                    self.drop_completed = False
                    writer.close()
                    break
                await write_frame(writer, {**response, "event": "completed"})
        finally:
            self.writers.discard(writer)
            self.tasks.discard(asyncio.current_task())
            writer.close()
            await writer.wait_closed()


def test_two_channels_authenticate_and_wait_for_completion():
    async def run():
        async with FakePi() as pi:
            client = CyNXClient(passphrase="test")
            try:
                await client.open("127.0.0.1", pi.command_port)
                result = await client.play_step("(0.1,0.2) L R", 0.3)
                assert result == {"completed": True, "id": 1}
                assert pi.executions == ["(0.1,0.2) L R"]
                assert (await client.command("status"))["last_completed_id"] == 1
            finally:
                await client.close()

    asyncio.run(run())


def test_expired_command_session_cannot_remain_ready_and_block_rediscovery():
    async def run():
        published = []
        async with FakePi() as pi:
            client = CyNXClient(passphrase="test", publish=published.append)
            await client.open("127.0.0.1", pi.command_port)
            pi.expired_session = True
            with pytest.raises(CyNXUnavailable):
                await client.command("status")
            assert client.abandoned and not client.ready
            assert client.fallback_ready_at > 0
            assert not published[-1]["network_connected"]
            assert not published[-1]["reconnecting"]

    asyncio.run(run())


def test_blank_auth_and_no_buffering_even_for_concurrent_callers():
    async def run():
        async with FakePi(passphrase="") as pi:
            pi.completion_gate = asyncio.Event()
            client = CyNXClient()
            tasks = []
            try:
                await client.open("127.0.0.1", pi.command_port)
                tasks = [
                    asyncio.create_task(client.play_step("A", 0.1)),
                    asyncio.create_task(client.play_step("B", 0.1)),
                ]
                async with asyncio.timeout(1):
                    while not pi.executions:
                        await asyncio.sleep(0)
                assert pi.executions == ["A"]
                assert not any(task.done() for task in tasks)
                pi.completion_gate.set()
                await asyncio.gather(*tasks)
                assert pi.executions == ["A", "B"]
            finally:
                pi.completion_gate.set()
                await asyncio.gather(*tasks, return_exceptions=True)
                await client.close()

    asyncio.run(run())


def test_usb_command_rejection_is_distinct_from_network_loss():
    async def run():
        async with FakePi() as pi:
            pi.reject_connect = True
            client = CyNXClient(passphrase="test")
            try:
                await client.open("127.0.0.1", pi.command_port)
                with pytest.raises(CyNXRejected, match="Switch is not awake"):
                    await client.command("connect")
                assert client.ready
                assert client.generation == 1
                assert (await client.command("status"))["identity"] == "cynx"
            finally:
                await client.close()

    asyncio.run(run())


def test_lost_completion_ack_resumes_without_replaying_step():
    async def run():
        async with FakePi(drop_completed=True) as pi:
            client = CyNXClient(passphrase="test")
            try:
                await client.open("127.0.0.1", pi.command_port)
                await client.play_step("A", 0.1)
                await client.play_step("B", 0.1)
                assert pi.executions == ["A", "B"]
                assert client.generation == 2
                assert client.last_completed_id == 2
            finally:
                await client.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "event",
    [
        {"event": "completed"},
        {"event": "accepted", "id": 9},
        {"event": "accepted", "id": True},
        {"event": "accepted", "session": "other"},
        {"event": "unexpected"},
    ],
)
def test_invalid_ack_is_not_treated_as_a_success_or_replayed(event):
    async def run():
        async with FakePi(bad_event=event) as pi:
            client = CyNXClient(passphrase="test")
            try:
                await client.open("127.0.0.1", pi.command_port)
                with pytest.raises(CyNXError):
                    await client.play_step("A", 0.1)
                assert pi.executions == []
                assert client.last_completed_id == 0
            finally:
                await client.close()

    asyncio.run(run())


def test_explicit_stop_is_not_a_transport_failure():
    async def run():
        async with FakePi(
            bad_event={"event": "failed", "ok": False, "code": "stopped"}
        ) as pi:
            client = CyNXClient(passphrase="test")
            try:
                await client.open("127.0.0.1", pi.command_port)
                with pytest.raises(CyNXStopped):
                    await client.play_step("A", 0.1)
                assert client.generation == 1
                assert not client.abandoned
            finally:
                await client.close()

    asyncio.run(run())


def test_terminal_usb_failure_is_not_replayed_as_a_reconnectable_step():
    async def run():
        async with FakePi(
            bad_event={"event": "failed", "ok": False, "code": "usb_unavailable"}
        ) as pi:
            client = CyNXClient(passphrase="test")
            try:
                await client.open("127.0.0.1", pi.command_port)
                with pytest.raises(CyNXUnavailable) as error:
                    await client.play_step("A", 0.1)
                assert client.generation == 1
                assert client.abandoned
                assert error.value.ready_at > 0
                assert not error.value.completed
                assert pi.executions == []
            finally:
                await client.close()

    asyncio.run(run())


def test_wrong_passphrase_closes_both_channels():
    async def run():
        async with FakePi() as pi:
            client = CyNXClient(passphrase="wrong")
            with pytest.raises(CyNXError, match="Authentication failed"):
                await client.open("127.0.0.1", pi.command_port)
            assert not client.ready
            assert pi.executions == []

    asyncio.run(run())


def test_reconnect_expiry_reports_completion_and_safe_takeover_deadline():
    async def run():
        client = CyNXClient()
        client.host = "127.0.0.1"
        client.session = "lost-session"
        client.status = {
            "reconnect_grace": 0,
            "heartbeat_timeout": 0.1,
            "recovery_timeout": 0.1,
        }
        client.mark_lost("Disconnected")
        with pytest.raises(CyNXUnavailable) as error:
            await client.recover()
        assert error.value.ready_at == client.fallback_ready_at
        assert client.abandoned

    asyncio.run(run())


@pytest.mark.parametrize("data", [b'{"ok":true}', b"[]\n", b"no-json\n"])
def test_bad_framing_is_rejected(data):
    async def run():
        reader = asyncio.StreamReader()
        reader.feed_data(data)
        reader.feed_eof()
        with pytest.raises(CyNXError):
            await read_frame(reader, 0.1)

    asyncio.run(run())


def test_split_frame_is_reassembled_and_oversized_frame_rejected():
    async def run():
        reader = asyncio.StreamReader(limit=16384)
        reader.feed_data(b'{"ok":')
        task = asyncio.create_task(read_frame(reader, 0.1))
        await asyncio.sleep(0)
        assert not task.done()
        reader.feed_data(b"true}\n")
        assert await task == {"ok": True}
        reader.feed_data(b"x" * 17000 + b"\n")
        with pytest.raises(CyNXError):
            await read_frame(reader, 0.1)

    asyncio.run(run())


def test_discovery_checks_nonce_identity_and_protocol():
    async def run():
        class Offers(asyncio.DatagramProtocol):
            def connection_made(self, transport):
                self.transport = transport

            def datagram_received(self, data, peer):
                request = json.loads(data)
                offer = {
                    "type": "cynx_offer",
                    "identity": "cynx",
                    "protocol": 1,
                    "nonce": request["nonce"],
                    "command_port": 3140,
                    "macro_port": 3141,
                }
                for bad in ({"nonce": "wrong"}, {"identity": "other"}, {"protocol": 2}):
                    self.transport.sendto(json.dumps({**offer, **bad}).encode(), peer)
                self.transport.sendto(json.dumps(offer).encode(), peer)

        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            Offers, local_addr=("127.0.0.1", 0)
        )
        try:
            port = transport.get_extra_info("sockname")[1]
            offers = await discover(port, 0.05, ["127.0.0.1"])
            assert [(host, command) for host, command, _ in offers] == [
                ("127.0.0.1", 3140)
            ]
        finally:
            transport.close()

    asyncio.run(run())


def test_remote_input_preserves_raw_waits_and_does_not_swallow_timeout():
    from cynthia.utils.nxbt_utils import Input

    async def run():
        remote = SimpleNamespace(play_input=AsyncMock())
        step = Input([], 1, 2)
        await step.play(remote, 0)
        remote.play_input.assert_awaited_once_with(step)
        remote.play_input.side_effect = CyNXUnavailable("No acknowledgment.")
        with pytest.raises(CyNXUnavailable):
            await step.play(remote, 0)

    asyncio.run(run())


def test_nested_macro_walk_preserves_individual_step_cursor():
    import nxbt

    from cynthia.utils.nxbt_utils import Input, Macro

    macro = Macro([Input(nxbt.Buttons.A)])
    macro.input_list = [Input(nxbt.Buttons.B), Macro([Input(nxbt.Buttons.X)])]
    assert [step.input_list for step in macro.walk()] == [
        [nxbt.Buttons.B],
        [nxbt.Buttons.X],
    ]


def test_explicit_and_generic_connect_commands_select_the_right_backend():
    from cynthia.bot.applications import nxbt as commands

    async def run():
        daemon = SimpleNamespace(
            connected=False,
            backend="none",
            connect=AsyncMock(return_value=True),
            disconnect=AsyncMock(return_value=True),
        )
        interaction = SimpleNamespace(
            client=SimpleNamespace(
                dman=SimpleNamespace(running_daemons={"NXBTDaemon": daemon})
            ),
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )
        daemon.backend = "cynx"
        await commands.cynx_connect_command.callback(interaction)
        daemon.connect.assert_awaited_with(backend="cynx")
        interaction.followup.send.assert_awaited_with(
            "Connected to Nintendo Switch via CyNX USB!"
        )
        await commands.nxbt_connect_command.callback(interaction)
        daemon.connect.assert_awaited_with(backend="nxbt")
        daemon.connected, daemon.backend = True, "nxbt"
        daemon.connect.reset_mock()
        await commands.connect.callback(interaction)
        daemon.connect.assert_not_awaited()
        await commands.cynx_disconnect_command.callback(interaction)
        daemon.disconnect.assert_awaited_with(backend="cynx")
        await commands.nxbt_disconnect_command.callback(interaction)
        daemon.disconnect.assert_awaited_with(backend="nxbt")

    asyncio.run(run())


def test_cynx_lifecycle_commands_are_owner_only_and_forward_requests():
    from cynthia.bot.applications import nxbt as commands

    async def run():
        daemon = SimpleNamespace(command=AsyncMock(return_value={}))
        interaction = SimpleNamespace(
            client=SimpleNamespace(
                dman=SimpleNamespace(running_daemons={"CyNXDaemon": daemon})
            ),
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )
        for command, name in (
            (commands.cynx_reboot_command, "reboot"),
            (commands.cynx_restart_command, "restart"),
        ):
            assert len(command.checks) >= 2
            await command.callback(interaction)
            daemon.command.assert_awaited_with(name)
            interaction.followup.send.assert_awaited_with(
                f"CyNX {name} requested.", ephemeral=True
            )

    asyncio.run(run())


@pytest.mark.parametrize("available", [False, True])
def test_cynx_status_uses_current_brand_for_live_and_cached_state(available):
    from cynthia.bot.applications import nxbt as commands

    state = {"version": "1.0", "uptime": 120, "switch_connected": True}
    daemon = SimpleNamespace(
        ns=SimpleNamespace(available=available),
        command=AsyncMock(return_value=state),
    )
    interaction = SimpleNamespace(
        client=SimpleNamespace(
            dman=SimpleNamespace(
                running_daemons={"CyNXDaemon": daemon},
                uns=SimpleNamespace(cynx_status=state),
            )
        ),
        response=SimpleNamespace(defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )

    asyncio.run(commands.cynx_status_command.callback(interaction))

    embed = interaction.followup.send.await_args.kwargs["embed"]
    assert embed.title == "CyNX status"
    assert embed.fields[0].value == ("Connected" if available else "Disconnected")
    assert embed.fields[1].value == state["version"]


@pytest.mark.parametrize("name", ["status", "reboot", "restart"])
def test_cynx_command_failures_use_current_brand(name):
    from discord import app_commands

    from cynthia.bot.applications import nxbt as commands

    daemon = SimpleNamespace(
        ns=SimpleNamespace(available=True),
        command=AsyncMock(side_effect=CyNXError("Controller unavailable.")),
    )
    interaction = SimpleNamespace(
        client=SimpleNamespace(
            dman=SimpleNamespace(running_daemons={"CyNXDaemon": daemon})
        ),
        response=SimpleNamespace(defer=AsyncMock()),
    )
    command = getattr(commands, f"cynx_{name}_command")

    with pytest.raises(app_commands.CheckFailure, match=f"CyNX {name} failed:"):
        asyncio.run(command.callback(interaction))


@pytest.mark.parametrize("backend", ["none", "nxbt", "cynx"])
def test_generic_disconnect_disables_pi_autoconnection_even_when_not_selected(backend):
    from queue import Queue

    from cynthia.daemons.nxbt import NXBTDaemon

    daemon = NXBTDaemon.__new__(NXBTDaemon)
    daemon.ns = SimpleNamespace(
        backend=backend, connected=False, epoch=0, allow_auto_cynx=True
    )
    daemon.cynx_requests = Queue()
    assert asyncio.run(daemon.disconnect())
    assert not daemon.ns.allow_auto_cynx
    requests = [
        daemon.cynx_requests.get_nowait(),
        daemon.cynx_requests.get_nowait(),
    ]
    assert [item["command"] for item in requests] == ["stop", "disconnect"]


def test_generic_disconnect_command_reaches_daemon_when_already_disconnected():
    from cynthia.bot.applications import nxbt as commands

    async def run():
        daemon = SimpleNamespace(
            connected=False, disconnect=AsyncMock(return_value=True)
        )
        interaction = SimpleNamespace(
            client=SimpleNamespace(
                dman=SimpleNamespace(running_daemons={"NXBTDaemon": daemon})
            ),
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )
        await commands.disconnect_controller(interaction)
        daemon.disconnect.assert_awaited_once_with()
        interaction.followup.send.assert_awaited_once_with(
            "Disconnected from Nintendo Switch."
        )

    asyncio.run(run())


@pytest.mark.parametrize("completed", [False, True])
def test_worker_bluetooth_fallback_preserves_the_uncompleted_step(
    monkeypatch, tmp_path, completed
):
    """A lost Pi must not skip the current input or replay a confirmed input."""
    from queue import Queue

    import nxbt

    from cynthia.daemons import nxbt as worker
    from cynthia.utils.drive import Drive
    from cynthia.utils.nxbt_utils import Macro

    events = []
    uns = SimpleNamespace(
        cynx_network_connected=True,
        cynx_switch_connected=True,
        cynx_reconnecting=False,
        cynx_fallback_ready_at=0,
    )

    def initialize(self, dman, *args, **kwargs):
        self.ns, self.uns = SimpleNamespace(run=True), dman.uns

    class Pi:
        def __init__(self, *args):
            pass

        @property
        def state(self):
            return {0: {"state": "connected"}}

        async def play_input(self, step):
            button = step.input_list[0]
            events.append(("pi", button))
            if button == nxbt.Buttons.B:
                uns.cynx_network_connected = False
                raise CyNXUnavailable("Link failed", completed=completed)

    class Bluetooth:
        state = {0: {"state": "connected"}}

        def press_buttons(self, controller, buttons, **kwargs):
            events.append(("bt", buttons[0]))
            if buttons == [nxbt.Buttons.X]:
                daemon.ns.run = False

        def _on_exit(self):
            events.append(("cleanup", None))

    async def connect(nx):
        events.append(("connect", None))
        return True, 0

    monkeypatch.setattr(worker.Daemon, "__init__", initialize)
    monkeypatch.setattr(worker.NXBTDaemon, "start", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker.multiprocessing, "Queue", Queue)
    monkeypatch.setattr(worker, "CyNXController", Pi)
    monkeypatch.setattr(worker.nxbt, "Nxbt", Bluetooth)
    monkeypatch.setattr(worker, "nxbt_connect", connect)
    monkeypatch.setattr(worker, "nxbt_disconnect", AsyncMock(return_value=True))
    monkeypatch.setattr(worker, "cynx_connect_setup", AsyncMock())
    monkeypatch.setattr(worker.os, "setpriority", lambda *args: None)
    dman = SimpleNamespace(
        uns=uns,
        manager=SimpleNamespace(dict=dict),
        drive=Drive(tmp_path),
        context=SimpleNamespace(config={}),
    )
    old_tree = Macro._macro_tree
    try:
        daemon = worker.NXBTDaemon(dman)
        daemon.ns.pause = False
        daemon.queue("A\nB\nX")
        daemon.loop(daemon.ns, uns, daemon.tqueue, Macro._macro_tree, dman.drive)
        expected = [("pi", nxbt.Buttons.A), ("pi", nxbt.Buttons.B), ("connect", None)]
        if not completed:
            expected.append(("bt", nxbt.Buttons.B))
        expected.extend([("bt", nxbt.Buttons.X), ("cleanup", None)])
        assert events == expected
        assert daemon.ns.done
    finally:
        Macro._macro_tree = old_tree


@pytest.mark.parametrize("repeat_event", [True, False])
def test_network_daemon_keeps_heartbeat_alive_during_a_step(monkeypatch, repeat_event):
    from queue import Queue

    from cynthia.daemons import cynx as daemon

    async def run():
        queue, replies, alerts = Queue(), {}, Queue()
        ns = SimpleNamespace(run=True, want_connected=True, available=False)
        uns = SimpleNamespace(controller_backend="none")
        release = asyncio.Event()
        statuses = []

        class Client:
            def __init__(self, settings, *, passphrase, publish):
                self.publish = publish
                self.ready = False
                self.session = None
                self.abandoned = False
                self.active_step = False
                self.fallback_ready_at = 0
                self.generation = 0

            async def find(self):
                self.ready, self.session = True, "session"

            async def command(self, command):
                statuses.append(command)
                state = {
                    "identity": "cynx",
                    "network_connected": True,
                    "switch_connected": True,
                    "spoofing": True,
                    "boot_id": "boot",
                    "errors": [
                        {
                            "id": 1 if repeat_event else statuses.count("status"),
                            "message": "USB test-passphrase failed",
                        }
                    ],
                }
                self.publish(state)
                if command == "stop":
                    release.set()
                return state

            async def play_step(self, text, duration):
                self.active_step = True
                await release.wait()
                self.active_step = False
                raise CyNXStopped("Stopped")

            async def close(self):
                self.ready = False

        monkeypatch.setattr(daemon, "CyNXClient", Client)
        runner = asyncio.create_task(
            daemon.run_client(
                ns,
                uns,
                queue,
                replies,
                {"cynx_heartbeat_interval": 0.01},
                "test-passphrase",
                alerts,
            )
        )
        try:
            queue.put({"id": "step", "command": "step", "step": "A", "duration": 30})
            async with asyncio.timeout(1):
                while statuses.count("status") < 3:
                    await asyncio.sleep(0.01)
                queue.put({"id": "stop", "command": "stop"})
                while "step" not in replies or "stop" not in replies:
                    await asyncio.sleep(0.01)
            assert replies["step"]["kind"] == "stopped"
            assert replies["stop"]["ok"]
            assert uns.cynx_network_connected
            assert alerts.qsize() == 1
            assert alerts.get_nowait() == {"message": "USB [redacted] failed"}
        finally:
            ns.run = False
            await runner
        assert ns.done
        assert statuses[-1] == "release"

    asyncio.run(run())


@pytest.mark.parametrize("age,skip_cleanup", [(0, True), (5, False)])
def test_network_daemon_releases_an_active_session_before_closing(
    monkeypatch, age, skip_cleanup
):
    import time
    from queue import Queue
    from unittest.mock import AsyncMock, Mock

    from cynthia.daemons import cynx as daemon

    async def run():
        queue, replies, alerts = Queue(), {}, Queue()
        ns = SimpleNamespace(run=True, want_connected=True, available=False)
        uns = SimpleNamespace(
            controller_backend="none",
            cv_frame_time=time.time() - age,
            ssim_scores=[("change_grip_order", 1.0)],
        )
        started = asyncio.Event()
        events = []

        async def play_step(text, duration):
            started.set()
            await asyncio.Event().wait()

        async def close():
            events.append("close")
            client.ready = False

        async def command(name, **fields):
            assert client.ready
            expected = (
                {"skip_cleanup": True}
                if skip_cleanup and name in ("disconnect", "release")
                else {}
            )
            assert fields == expected
            events.append(name)
            return {"spoofing": True}

        client = SimpleNamespace(
            ready=True,
            generation=0,
            command=AsyncMock(side_effect=command),
            play_step=play_step,
            close=AsyncMock(side_effect=close),
            mark_lost=Mock(),
        )
        monkeypatch.setattr(daemon, "CyNXClient", Mock(return_value=client))
        runner = asyncio.create_task(
            daemon.run_client(ns, uns, queue, replies, {}, "", alerts)
        )
        queue.put({"id": "step", "command": "step", "step": "A", "duration": 30})
        await asyncio.wait_for(started.wait(), 1)
        queue.put({"id": "disconnect", "command": "disconnect"})
        async with asyncio.timeout(1):
            while "disconnect" not in replies:
                await asyncio.sleep(0.01)
        assert replies["disconnect"]["ok"]
        ns.run = False
        await asyncio.wait_for(runner, 1)
        client.mark_lost.assert_not_called()
        assert events[-2:] == ["release", "close"]
        assert ns.done

    asyncio.run(run())


@pytest.mark.parametrize("auto_connect", [False, True])
def test_autoconnect_toggle_preserves_manual_connect_and_tracks_reconnects(
    monkeypatch, auto_connect
):
    from queue import Queue
    from unittest.mock import AsyncMock, Mock

    from cynthia.daemons import cynx as worker

    def initialize(self, dman, *args, **kwargs):
        self.ns, self.uns = SimpleNamespace(run=True), dman.uns

    monkeypatch.setattr(worker.Daemon, "__init__", initialize)
    monkeypatch.setattr(worker.CyNXDaemon, "start", lambda self: None)
    dman = SimpleNamespace(
        uns=SimpleNamespace(controller_backend="none"),
        cynx_requests=Queue(),
        cynx_replies={},
        cynx_alerts=Queue(),
        context=SimpleNamespace(env={}, config={"cynx_auto_connect": auto_connect}),
    )
    daemon = worker.CyNXDaemon(dman)

    async def run():
        bound = False
        statuses = 0
        publish_state = None

        async def command(name):
            nonlocal bound, statuses
            if name == "connect":
                bound = True
            elif name == "release":
                bound = False
            elif name == "status":
                statuses += 1
            state = {
                "network_connected": True,
                "switch_connected": bound,
                "spoofing": bound,
            }
            publish_state(state)
            return state

        client = SimpleNamespace(
            ready=True,
            generation=0,
            command=AsyncMock(side_effect=command),
            close=AsyncMock(),
        )

        def make_client(settings, *, passphrase, publish):
            nonlocal publish_state
            publish_state = publish
            return client

        monkeypatch.setattr(worker, "CyNXClient", Mock(side_effect=make_client))
        runner = asyncio.create_task(
            worker.run_client(
                daemon.ns,
                dman.uns,
                dman.cynx_requests,
                dman.cynx_replies,
                {"cynx_heartbeat_interval": 0.01},
                "",
            )
        )
        try:
            async with asyncio.timeout(1):
                while statuses < 3:
                    await asyncio.sleep(0.01)
                assert bound is auto_connect
                assert dman.uns.cynx_connect_count == int(auto_connect)
                dman.cynx_requests.put({"id": "manual", "command": "connect"})
                while "manual" not in dman.cynx_replies:
                    await asyncio.sleep(0.01)
                assert dman.cynx_replies["manual"]["ok"]
                assert bound
                assert dman.uns.cynx_connect_count == 1
                bound = False
                while dman.uns.cynx_connect_count < 2:
                    await asyncio.sleep(0.01)
                assert bound
        finally:
            daemon.ns.run = False
            await runner

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["manual", "startup", "reconnect"])
def test_worker_finishes_each_cynx_connection_once(monkeypatch, tmp_path, mode):
    from queue import Queue

    from cynthia.daemons import nxbt as worker
    from cynthia.utils.drive import Drive
    from cynthia.utils.nxbt_utils import Macro

    uns = SimpleNamespace(
        cynx_network_connected=True,
        cynx_switch_connected=True,
        cynx_reconnecting=False,
        cynx_connect_count=1,
    )

    def initialize(self, dman, *args, **kwargs):
        self.ns, self.uns = SimpleNamespace(run=True), dman.uns

    calls = []

    async def setup(*args):
        calls.append(uns.cynx_connect_count)

    async def tick(_):
        if mode == "reconnect" and calls == [1]:
            uns.cynx_connect_count = 2
        elif calls:
            daemon.ns.run = False

    monkeypatch.setattr(worker.Daemon, "__init__", initialize)
    monkeypatch.setattr(worker.NXBTDaemon, "start", lambda *a, **k: None)
    monkeypatch.setattr(worker.multiprocessing, "Queue", Queue)
    monkeypatch.setattr(worker, "cynx_connect_setup", setup)
    monkeypatch.setattr(
        worker, "cynx_request", AsyncMock(return_value={"switch_connected": True})
    )
    monkeypatch.setattr(worker.asyncio, "sleep", tick)
    monkeypatch.setattr(worker.os, "setpriority", lambda *args: None)
    dman = SimpleNamespace(
        uns=uns,
        manager=SimpleNamespace(dict=dict),
        drive=Drive(tmp_path),
        context=SimpleNamespace(config={"cynx_auto_connect": mode != "manual"}),
    )
    old_tree = Macro._macro_tree
    try:
        daemon = worker.NXBTDaemon(dman)
        if mode == "manual":
            daemon.ns.connect = True
            daemon.ns.requested_backend = "cynx"
        daemon.loop(daemon.ns, uns, daemon.tqueue, Macro._macro_tree, dman.drive)
        assert calls == ([1, 2] if mode == "reconnect" else [1])
        assert daemon.ns.done
    finally:
        Macro._macro_tree = old_tree


@pytest.mark.parametrize(
    "scores,age,expected",
    [
        ([("change_grip_order", 1.0)], 0, True),
        ([("home", 1.0)], 0, False),
        ([("change_grip_order", 0.97)], 0, False),
        ([("change_grip_order", 1.0)], 5, False),
        ([], 0, False),
    ],
)
def test_connection_inputs_require_fresh_positive_cv(
    monkeypatch, scores, age, expected
):
    import time

    import nxbt

    from cynthia.utils import nxbt_utils

    steps = []

    async def play_input(step):
        steps.append(step)

    monkeypatch.setattr(nxbt_utils, "CYNX_CONNECT_CV_TIMEOUT", 0)
    monkeypatch.setattr(nxbt_utils.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(nxbt_utils.Macro, "_macro_tree", {})
    uns = SimpleNamespace(ssim_scores=scores, cv_frame_time=time.time() - age)
    played = asyncio.run(
        nxbt_utils.cynx_connect_setup(
            SimpleNamespace(play_input=play_input, state={0: {"state": "connected"}}),
            0,
            uns,
        )
    )
    assert played is expected
    if expected:
        assert [step.input_list for step in steps if step.input_list] == [
            [nxbt.Buttons.A],
            [nxbt.Buttons.A],
            [nxbt.Buttons.B],
            [nxbt.Buttons.HOME],
        ]
        assert sum(not step.input_list for step in steps) == 3
    else:
        assert not steps
