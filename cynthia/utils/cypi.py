"""Discover a CyPi and exchange acknowledged controller steps over two sockets."""

import asyncio
import contextlib
import itertools
import json
import logging
import secrets
import socket
import time
import uuid

logger = logging.getLogger(__name__)
FRAME_LIMIT = 16384
PROTOCOL = 1


class CyPiError(RuntimeError):
    """A rejected command or invalid response from a CyPi."""


class CyPiStopped(CyPiError):
    """Playback was explicitly cancelled rather than disconnected."""


class CyPiRejected(CyPiError):
    """The peer answered correctly but could not perform the requested command."""


class CyPiUnavailable(ConnectionError):
    """A session could not recover before its reconnect deadline."""

    def __init__(self, message, *, completed=False, ready_at=0):
        super().__init__(message)
        self.completed = completed
        self.ready_at = ready_at


async def read_frame(reader, timeout):
    """Read one bounded JSON object, rejecting truncated and malformed frames."""
    async with asyncio.timeout(timeout):
        try:
            line = await reader.readline()
        except (ValueError, asyncio.LimitOverrunError) as error:
            raise CyPiError("CyPi response exceeds the frame limit.") from error
    if not line:
        raise ConnectionError("CyPi closed the connection.")
    if len(line) > FRAME_LIMIT or not line.endswith(b"\n"):
        raise CyPiError("Invalid CyPi response framing.")
    try:
        frame = json.loads(line)
    except (ValueError, UnicodeError) as error:
        raise CyPiError("CyPi returned invalid JSON.") from error
    if not isinstance(frame, dict):
        raise CyPiError("CyPi response must be an object.")
    return frame


async def write_frame(writer, frame):
    """Write one bounded JSON frame without logging its authentication fields."""
    data = json.dumps(frame, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    if len(data) > FRAME_LIMIT:
        raise CyPiError("CyPi request exceeds the frame limit.")
    writer.write(data)
    await writer.drain()


async def discover(port=3140, timeout=1.0, addresses=None):
    """Broadcast on active IPv4 interfaces and return matching CyPi offers."""
    if addresses is None:
        addresses = {"255.255.255.255"}
        try:
            proc = await asyncio.create_subprocess_exec(
                "ip",
                "-j",
                "-4",
                "addr",
                "show",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            async with asyncio.timeout(2):
                output, _ = await proc.communicate()
            for interface in json.loads(output):
                for address in interface.get("addr_info", []):
                    if address.get("broadcast"):
                        addresses.add(address["broadcast"])
        except (OSError, ValueError, TimeoutError):
            logger.debug("Using limited broadcast for CyPi discovery.")
    nonce = secrets.token_hex(12)
    request = json.dumps(
        {"type": "cynx_discover", "protocol": PROTOCOL, "nonce": nonce}
    ).encode()
    offers = {}
    loop = asyncio.get_running_loop()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setblocking(False)
        sock.bind(("", 0))
        for address in addresses:
            with contextlib.suppress(OSError):
                await loop.sock_sendto(sock, request, (address, port))
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            try:
                async with asyncio.timeout(deadline - loop.time()):
                    data, peer = await loop.sock_recvfrom(sock, FRAME_LIMIT)
                offer = json.loads(data)
                if (
                    not isinstance(offer, dict)
                    or offer.get("type") != "cynx_offer"
                    or offer.get("identity") != "cypi"
                    or offer.get("protocol") != PROTOCOL
                    or offer.get("nonce") != nonce
                ):
                    continue
                command_port = offer.get("command_port")
                macro_port = offer.get("macro_port")
                if not all(
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and 0 < value < 65536
                    for value in (command_port, macro_port)
                ):
                    continue
                offers[(peer[0], command_port)] = offer
            except TimeoutError:
                break
            except (ValueError, UnicodeError):
                continue
    return [
        (host, command_port, offer) for (host, command_port), offer in offers.items()
    ]


class CyPiClient:
    """Own a command/heartbeat channel and a sequential, deduplicated macro channel."""

    def __init__(self, settings=None, *, passphrase="", publish=None):
        self.settings = settings or {}
        self.passphrase = passphrase or ""
        self.publish = publish or (lambda state: None)
        self.session = None
        self.status = {}
        self.host = None
        self.command_port = self.settings.get("cypi_command_port", 3140)
        self.macro_port = self.settings.get("cypi_macro_port", 3141)
        self.reader = self.writer = None
        self.macro_reader = self.macro_writer = None
        self._request_ids = itertools.count(1)
        self._step_id = 0
        self._command_lock = asyncio.Lock()
        self._step_lock = asyncio.Lock()
        self._reconnect_lock = asyncio.Lock()
        self._failure_at = None
        self.fallback_ready_at = 0
        self.active_step = False
        self.abandoned = False
        self.last_completed_id = 0
        self.generation = 0

    @property
    def ready(self):
        """Report open network channels, not whether USB spoofing is active."""
        return (
            self.writer is not None
            and not self.writer.is_closing()
            and self.macro_writer is not None
            and not self.macro_writer.is_closing()
        )

    def _publish(self, **changes):
        state = dict(self.status)
        state.update(changes)
        self.publish(state)

    def _safe_error(self, message):
        message = str(message)
        return (
            message.replace(self.passphrase, "[redacted]")
            if self.passphrase
            else message
        )

    def _update(self, status):
        self.status = status
        self.last_completed_id = max(
            self.last_completed_id, int(status.get("last_completed_id", 0))
        )
        self._publish(
            network_connected=True,
            reconnecting=False,
            host=self.host,
            fallback_ready_at=0,
            error="",
        )

    async def close(self):
        """Close both channels, retaining session identity for a bounded resume."""
        writers = [self.writer, self.macro_writer]
        self.reader = self.writer = None
        self.macro_reader = self.macro_writer = None
        for writer in writers:
            if writer is not None:
                writer.close()
        for writer in writers:
            if writer is not None:
                with contextlib.suppress(OSError, TimeoutError):
                    async with asyncio.timeout(1):
                        await writer.wait_closed()

    async def _rpc(self, command, *, timeout=2, **fields):
        async with self._command_lock:
            if self.writer is None:
                raise ConnectionError("CyPi command channel is closed.")
            reader, writer = self.reader, self.writer
            request_id = next(self._request_ids)
            async with asyncio.timeout(timeout):
                await write_frame(
                    writer, {"id": request_id, "command": command, **fields}
                )
                response = await read_frame(reader, timeout)
            if type(response.get("id")) is not int or response["id"] != request_id:
                raise CyPiError("CyPi command acknowledgment ID does not match.")
            if response.get("ok") is not True:
                details = response.get("result") or {}
                if response.get("code") == "session_expired":
                    self.last_completed_id = max(
                        self.last_completed_id, int(details.get("last_completed_id", 0))
                    )
                    self.mark_lost("CyPi session expired.")
                    self.abandoned = True
                    await self.close()
                    self._publish(
                        network_connected=False,
                        reconnecting=False,
                        error="CyPi session expired.",
                        fallback_ready_at=self.fallback_ready_at,
                    )
                    raise CyPiUnavailable(
                        "CyPi session expired.", ready_at=self.fallback_ready_at
                    )
                raise CyPiRejected(
                    self._safe_error(
                        response.get("error", "CyPi rejected the command.")
                    )
                )
            result = response.get("result")
            if not isinstance(result, dict):
                raise CyPiError("CyPi command result must be an object.")
            return result

    async def open(self, host, command_port=None, *, resume=False, timeout=2):
        """Authenticate both channels without implicitly binding USB."""
        await self.close()
        self.host = host
        self.command_port = command_port or self.command_port
        old_session = self.session if resume else None
        self.reader, self.writer = await asyncio.wait_for(
            asyncio.open_connection(host, self.command_port, limit=FRAME_LIMIT),
            timeout,
        )
        try:
            result = await self._rpc(
                "hello",
                protocol=PROTOCOL,
                passphrase=self.passphrase,
                session=old_session,
                timeout=timeout,
            )
            if result.get("identity") != "cypi" or result.get("protocol") != PROTOCOL:
                raise CyPiError("The discovered host is not a compatible CyPi.")
            session = result.get("session")
            if not isinstance(session, str) or not session:
                raise CyPiError("CyPi did not assign a session.")
            if resume and session != old_session:
                raise CyPiUnavailable("CyPi lost the previous playback session.")
            self.session = session
            self.macro_port = int(result.get("macro_port", self.macro_port))
            self.macro_reader, self.macro_writer = await asyncio.wait_for(
                asyncio.open_connection(host, self.macro_port, limit=FRAME_LIMIT),
                timeout,
            )
            await write_frame(
                self.macro_writer,
                {
                    "id": 0,
                    "command": "attach",
                    "session": session,
                    "passphrase": self.passphrase,
                },
            )
            attached = await read_frame(self.macro_reader, timeout)
            if (
                attached.get("id") != 0
                or attached.get("ok") is not True
                or (attached.get("result") or {}).get("session") != session
            ):
                raise CyPiError("CyPi rejected the macro channel.")
            if not resume:
                self._step_id = 0
                self.last_completed_id = 0
            self._failure_at = None
            self.abandoned = False
            self.generation += 1
            self._update(result)
            return result
        except BaseException:
            await self.close()
            raise

    async def find(self):
        """Find and authenticate the first available compatible Pi on the LAN."""
        offers = await discover(
            self.settings.get("cypi_command_port", 3140),
            self.settings.get("cypi_discovery_timeout", 1.0),
        )
        for host, port, _ in offers:
            try:
                return await self.open(host, port)
            except (OSError, CyPiError) as error:
                logger.debug("CyPi offer from %s could not connect: %s", host, error)
                await self.close()
        raise CyPiUnavailable("No available CyPi found on the LAN.")

    async def command(self, command, *, timeout=None, **fields):
        """Run an explicit command; lifecycle commands have a longer deadline."""
        timeout = timeout or (
            15 if command in ("connect", "disconnect", "release") else 2
        )
        result = await self._rpc(command, timeout=timeout, **fields)
        if "identity" in result:
            self._update(result)
        return result

    def mark_lost(self, error):
        """Start one recovery deadline shared by heartbeat and playback."""
        if self._failure_at is None:
            self._failure_at = time.monotonic()
            self.fallback_ready_at = (
                self._failure_at
                + self.status.get("heartbeat_timeout", 3)
                + self.status.get("reconnect_grace", 5)
                + self.status.get("recovery_timeout", 10)
                + 1
            )
        self._publish(
            network_connected=False,
            reconnecting=True,
            host=self.host,
            error=str(error),
            fallback_ready_at=self.fallback_ready_at,
        )

    async def recover(self):
        """Resume the same session, never replace it with a new playback session."""
        async with self._reconnect_lock:
            if self.ready and self._failure_at is None:
                return
            if self.abandoned:
                raise CyPiUnavailable(
                    "CyPi reconnect grace expired.", ready_at=self.fallback_ready_at
                )
            self.mark_lost("CyPi connection interrupted.")
            deadline = self._failure_at + self.status.get("reconnect_grace", 5)
            while time.monotonic() < deadline:
                try:
                    await self.open(
                        self.host,
                        resume=True,
                        timeout=min(1, max(0.05, deadline - time.monotonic())),
                    )
                    return
                except CyPiUnavailable:
                    break
                except (OSError, CyPiError):
                    await asyncio.sleep(0.1)
            await self.close()
            self.abandoned = True
            logger.warning(
                "CyPi session lost; waiting for recovery before Bluetooth takeover."
            )
            self._publish(
                network_connected=False,
                reconnecting=False,
                host=self.host,
                error="CyPi unavailable; waiting for safe Bluetooth takeover.",
                fallback_ready_at=self.fallback_ready_at,
            )
            raise CyPiUnavailable(
                "CyPi reconnect grace expired.", ready_at=self.fallback_ready_at
            )

    async def play_step(self, text, duration):
        """Require accepted and completed events; resume a dropped ACK without replay."""
        async with self._step_lock:
            if not self.ready or self.abandoned:
                raise CyPiUnavailable(
                    "CyPi is unavailable.", ready_at=self.fallback_ready_at
                )
            self.active_step = True
            self._step_id += 1
            step_id, session = self._step_id, self.session
            try:
                while True:
                    generation = self.generation
                    try:
                        if self.session != session:
                            raise CyPiUnavailable("CyPi playback session changed.")
                        if self.last_completed_id >= step_id:
                            return {"completed": True, "id": step_id}
                        reader, writer = self.macro_reader, self.macro_writer
                        if reader is None or writer is None:
                            raise ConnectionError("CyPi macro channel is closed.")
                        async with asyncio.timeout(2):
                            await write_frame(
                                writer,
                                {"id": step_id, "session": session, "step": text},
                            )
                        accepted = False
                        while True:
                            response = await read_frame(
                                reader, max(2, duration + 2) if accepted else 2
                            )
                            if (
                                type(response.get("id")) is not int
                                or response["id"] != step_id
                                or response.get("session") != session
                            ):
                                raise CyPiError(
                                    "CyPi step acknowledgment does not match."
                                )
                            if response.get("ok") is not True:
                                code = response.get("code")
                                if code in ("stopped", "cancelled"):
                                    raise CyPiStopped("CyPi playback was stopped.")
                                if code in (
                                    "interrupted",
                                    "session_expired",
                                    "usb_unavailable",
                                    "usb_disconnected",
                                    "not_connected",
                                ):
                                    self.mark_lost("CyPi interrupted the input.")
                                    await self.close()
                                    self.abandoned = True
                                    self._publish(
                                        network_connected=False,
                                        reconnecting=False,
                                        fallback_ready_at=self.fallback_ready_at,
                                        error="CyPi interrupted the input.",
                                    )
                                    raise CyPiUnavailable("CyPi interrupted the input.")
                                raise CyPiError(
                                    self._safe_error(
                                        response.get("error", "CyPi rejected input.")
                                    )
                                )
                            event = response.get("event")
                            if event == "accepted" and not accepted:
                                accepted = True
                            elif event == "completed" and accepted:
                                self.last_completed_id = step_id
                                return {"completed": True, "id": step_id}
                            else:
                                raise CyPiError(
                                    "Invalid CyPi step acknowledgment order."
                                )
                    except CyPiUnavailable:
                        raise
                    except (OSError, TimeoutError) as error:
                        if generation != self.generation and self.ready:
                            continue
                        self.mark_lost(error)
                        await self.recover()
            except CyPiUnavailable as error:
                raise CyPiUnavailable(
                    str(error),
                    completed=self.last_completed_id >= step_id,
                    ready_at=self.fallback_ready_at,
                ) from error
            finally:
                self.active_step = False


async def request(queue, replies, command, *, timeout=90, **fields):
    """Send an IPC request to the network daemon without sharing socket ownership."""
    if queue is None or replies is None:
        raise CyPiUnavailable("CyPi daemon is not available.")
    request_id = uuid.uuid4().hex
    queue.put({"id": request_id, "command": command, **fields})
    try:
        async with asyncio.timeout(timeout):
            while request_id not in replies:
                await asyncio.sleep(0.025)
        response = replies.pop(request_id)
    except BaseException:
        queue.put({"id": None, "command": "cancel_request", "request_id": request_id})
        raise
    if not response.get("ok"):
        kind = response.get("kind")
        if kind == "unavailable":
            raise CyPiUnavailable(
                response.get("error", "CyPi is unavailable."),
                completed=response.get("completed", False),
                ready_at=response.get("ready_at", 0),
            )
        if kind == "stopped":
            raise CyPiStopped(response.get("error", "Playback stopped."))
        raise CyPiError(response.get("error", "CyPi command failed."))
    return response.get("result", {})


class CyPiController:
    """Adapt existing macro playback to the CyPi daemon's checked step transport."""

    def __init__(self, queue, replies, uns):
        self.queue, self.replies, self.uns = queue, replies, uns

    @property
    def state(self):
        connected = getattr(self.uns, "cypi_network_connected", False) and getattr(
            self.uns, "cypi_switch_connected", False
        )
        return {0: {"state": "connected" if connected else "disconnected"}}

    async def play_input(self, input_step):
        return await request(
            self.queue,
            self.replies,
            "step",
            step=str(input_step),
            duration=input_step.down_duration + input_step.up_duration,
            timeout=input_step.down_duration + input_step.up_duration + 45,
        )

    def press_buttons(self, controller, buttons, *, down, up, block=True):
        """Support existing HOME-menu recovery, called in a worker thread."""
        from cynthia.utils.nxbt_utils import Input

        return asyncio.run(self.play_input(Input(buttons, down, up, block)))
