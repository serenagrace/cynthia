"""Discover a CyPi, monitor its heartbeat, and own its two network channels."""

import asyncio
import contextlib
import logging
import time
from collections import deque
from queue import Empty, Full

from cynthia.utils.cypi import (
    CyPiClient,
    CyPiError,
    CyPiRejected,
    CyPiStopped,
    CyPiUnavailable,
    request,
)
from cynthia.utils.log import setup_logging
from cynthia.utils.nxbt_utils import shows_change_grip_order

from .daemon import Daemon

logger = logging.getLogger(__name__)


async def run_client(ns, uns, queue, replies, settings, passphrase, alerts=None):
    """Keep socket ownership in one process while servicing playback IPC."""
    jobs = {}
    seen_errors = deque(maxlen=256)
    recent_alerts = deque(maxlen=64)

    def relay_errors(state):
        if alerts is None:
            return
        for error in state.get("errors", []):
            if not isinstance(error, dict) or not isinstance(error.get("message"), str):
                continue
            key = (state.get("boot_id"), error.get("id"))
            if key in seen_errors:
                continue
            seen_errors.append(key)
            message = error["message"]
            if passphrase:
                message = message.replace(passphrase, "[redacted]")
            logger.error("CyPi: %s", message)
            now = time.monotonic()
            if any(
                previous == message and now - sent_at < 60
                for previous, sent_at in recent_alerts
            ):
                continue
            recent_alerts.append((message, now))
            item = {"message": message[:1500]}
            try:
                alerts.put_nowait(item)
            except Full:
                with contextlib.suppress(Empty):
                    alerts.get_nowait()
                with contextlib.suppress(Full):
                    alerts.put_nowait(item)

    def publish(state):
        relay_errors(state)
        connected = bool(
            state.get("network_connected") and state.get("switch_connected")
        )
        if connected and not getattr(uns, "cypi_switch_connected", False):
            uns.cypi_connect_count = getattr(uns, "cypi_connect_count", 0) + 1
        uns.cypi_status = state
        uns.cypi_network_connected = state.get("network_connected", False)
        uns.cypi_switch_connected = connected
        uns.cypi_reconnecting = state.get("reconnecting", False)
        uns.cypi_fallback_ready_at = state.get("fallback_ready_at", 0)
        uns.cypi_error = state.get("error", "")
        ns.available = bool(state.get("network_connected"))

    client = CyPiClient(settings, passphrase=passphrase, publish=publish)

    async def handle(item, job_key):
        command = item["command"]
        request_id = item.get("id")
        try:
            if command == "step":
                result = await client.play_step(item["step"], item["duration"])
            else:
                if command == "connect":
                    ns.want_connected = True
                elif command == "disconnect":
                    ns.want_connected = False
                if not client.ready:
                    raise CyPiUnavailable(
                        "CyPi is not connected.",
                        ready_at=client.fallback_ready_at,
                    )
                fields = {}
                if command in ("disconnect", "release") and shows_change_grip_order(
                    uns
                ):
                    fields["skip_cleanup"] = True
                result = await client.command(command, **fields)
            response = {"ok": True, "result": result}
        except CyPiUnavailable as error:
            response = {
                "ok": False,
                "kind": "unavailable",
                "error": str(error),
                "completed": error.completed,
                "ready_at": error.ready_at,
            }
        except CyPiStopped as error:
            response = {"ok": False, "kind": "stopped", "error": str(error)}
        except (OSError, CyPiError, ValueError) as error:
            if command == "step" and client.ready:
                with contextlib.suppress(OSError, CyPiError):
                    await client.command("stop")
            response = {"ok": False, "kind": "error", "error": str(error)}
        except asyncio.CancelledError:
            if command == "step" and ns.run:
                client.mark_lost("Controller request was cancelled.")
                await client.close()
            return
        except Exception as error:
            logger.exception("CyPi request failed")
            response = {"ok": False, "kind": "error", "error": str(error)}
        finally:
            jobs.pop(job_key, None)
        if request_id is not None:
            replies[request_id] = response

    def start_job(item):
        key = item.get("id") or object()
        jobs[key] = asyncio.create_task(handle(item, key))

    async def maintain():
        while ns.run:
            generation = client.generation
            try:
                if not client.ready:
                    if client.session and not client.abandoned:
                        await client.recover()
                    else:
                        if (
                            client.active_step
                            or time.monotonic() < client.fallback_ready_at
                        ):
                            await asyncio.sleep(0.1)
                            continue
                        await client.find()
                state = await client.command("status")
                if (
                    state.get("recovering")
                    or state.get("connection_state") == "reconnecting"
                ):
                    client.mark_lost("CyPi reported an interrupted network session.")
                    await client.recover()
                    continue
                backend = getattr(uns, "controller_backend", "none")
                if (
                    ns.want_connected
                    and not state.get("spoofing")
                    and backend in ("none", "cypi")
                ):
                    await client.command("connect")
                await asyncio.sleep(settings.get("cypi_heartbeat_interval", 1.0))
            except CyPiUnavailable as error:
                logger.debug("%s", error)
                await asyncio.sleep(settings.get("cypi_discovery_interval", 2.0))
            except CyPiRejected as error:
                uns.cypi_error = str(error)
                logger.debug("CyPi command could not complete: %s", error)
                await asyncio.sleep(settings.get("cypi_discovery_interval", 2.0))
            except (OSError, CyPiError, ValueError) as error:
                if generation != client.generation and client.ready:
                    continue
                if client.session and not client.abandoned:
                    client.mark_lost(error)
                    with contextlib.suppress(CyPiUnavailable):
                        await client.recover()
                else:
                    publish(
                        {
                            "network_connected": False,
                            "reconnecting": False,
                            "error": str(error),
                            "fallback_ready_at": client.fallback_ready_at,
                        }
                    )
                await asyncio.sleep(settings.get("cypi_discovery_interval", 2.0))

    heartbeat = asyncio.create_task(maintain())
    try:
        while ns.run:
            for _ in range(32):
                try:
                    item = queue.get_nowait()
                except Empty:
                    break
                if item["command"] == "cancel_request":
                    old_id = item["request_id"]
                    old = jobs.pop(old_id, None)
                    if old is not None:
                        old.cancel()
                    replies.pop(old_id, None)
                    if client.ready:
                        start_job({"id": None, "command": "stop"})
                else:
                    start_job(item)
            if heartbeat.done():
                heartbeat.result()
            await asyncio.sleep(0.025)
    finally:
        heartbeat.cancel()
        for job in list(jobs.values()):
            job.cancel()
        await asyncio.gather(heartbeat, *list(jobs.values()), return_exceptions=True)
        if client.ready:
            with contextlib.suppress(OSError, CyPiError):
                fields = {}
                if shows_change_grip_order(uns):
                    fields["skip_cleanup"] = True
                await client.command("release", **fields)
        await client.close()
        publish({"network_connected": False, "reconnecting": False, "error": ""})
        ns.done = True


class CyPiDaemon(Daemon):
    """Expose checked Pi commands while a child process handles discovery."""

    def __init__(self, dman):
        settings = {
            key: value
            for key, value in dman.context.config.items()
            if key.startswith("cypi_")
        }
        self.requests = dman.cypi_requests
        self.replies = dman.cypi_replies
        self.alerts = dman.cypi_alerts
        passphrase = dman.context.env.get("CYPI_PASSPHRASE", "") or ""
        super().__init__(
            dman, self.requests, self.replies, settings, passphrase, self.alerts
        )
        self.ns.available = False
        self.ns.done = False
        self.ns.want_connected = bool(settings.get("cypi_auto_connect", True))
        self.uns.cypi_connect_count = 0
        self.uns.cypi_network_connected = False
        self.uns.cypi_switch_connected = False
        self.uns.cypi_reconnecting = False
        self.uns.cypi_fallback_ready_at = 0
        self.uns.cypi_status = {}
        self.uns.cypi_error = ""
        self.start()

    @staticmethod
    def loop(ns, uns, queue, replies, settings, passphrase, alerts):
        setup_logging()
        if not settings.get("cypi_enabled", True):
            while ns.run:
                try:
                    item = queue.get_nowait()
                    if item.get("id") is not None:
                        replies[item["id"]] = {
                            "ok": False,
                            "kind": "unavailable",
                            "error": "CyPi discovery is disabled in config.yaml.",
                        }
                except Empty:
                    pass
                time.sleep(0.1)
            ns.done = True
            return
        asyncio.run(run_client(ns, uns, queue, replies, settings, passphrase, alerts))

    async def command(self, command):
        return await request(self.requests, self.replies, command, timeout=30)
