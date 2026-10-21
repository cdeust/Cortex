"""The store broker's server: connections, handshake, dispatch, idle exit.

Transport-neutral: ``accept`` returns an authenticated channel (Unix socket
with kernel peer UID, or Windows named pipe restricted to the user's SID).
One thread per connection reads requests in order; ``workers`` threads run
them through the ``Scheduler``. Every request is one unit of work on the
broker's own store, so no client ever holds a transaction or a lock between
requests, and the database sees at most the store's pool, whatever the
number of clients (ADR-1112).

source: ADR-1112 (broker and versioned schema)
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mcp_server.infrastructure.broker_protocol import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    PROTOCOL_VERSION,
    ProtocolError,
    check_request,
    dumps,
    loads,
)
from mcp_server.infrastructure.broker_scheduler import Scheduler, SchedulerPolicy, Task

logger = logging.getLogger("cortex.store_broker")

# source: ADR-1112 the client must speak within this budget after connecting
HANDSHAKE_SECONDS = 10.0


@dataclass(frozen=True)
class ServerPolicy:
    scheduler: SchedulerPolicy
    idle_seconds: float
    max_connections: int


@dataclass(frozen=True)
class Identity:
    """What the broker announces in ``welcome``."""

    revision: str
    schema_version: int


Accept = Callable[[], Any]  # returns a channel; raises OSError when closed
Execute = Callable[[str, str, list, dict, str], Any]


class BrokerServer:
    def __init__(
        self,
        accept: Accept,
        execute: Execute,
        policy: ServerPolicy,
        identity: Identity,
        peer_label: Callable[[Any], str] = lambda channel: "peer",
        refusal: tuple[str, str] | None = None,
    ) -> None:
        self._accept = accept
        self._execute = execute
        self._policy = policy
        self._identity = identity
        self._peer_label = peer_label
        # (type, message) of the failure that kept the store closed: every
        # client is told why, then the broker exits once idle (decision 7)
        self._refusal = refusal
        self._scheduler = Scheduler(policy.scheduler)
        self._lock = threading.Lock()
        self._connections = 0
        self._last_activity = time.monotonic()
        self._stopping = threading.Event()
        self._draining = threading.Event()

    # ── connections ────────────────────────────────────────────────────

    def _touch(self) -> None:
        with self._lock:
            self._last_activity = time.monotonic()

    def _admit(self) -> bool:
        with self._lock:
            if self._connections >= self._policy.max_connections:
                return False
            self._connections += 1
            self._last_activity = time.monotonic()
            return True

    def _release(self) -> None:
        with self._lock:
            self._connections -= 1
            self._last_activity = time.monotonic()

    def _send(self, channel: Any, message: dict[str, Any]) -> None:
        channel.send_frame(dumps(message), MAX_RESPONSE_BYTES, None)

    def _handshake(self, channel: Any) -> dict[str, Any]:
        deadline = time.monotonic() + HANDSHAKE_SECONDS
        hello = loads(channel.recv_frame(MAX_REQUEST_BYTES, deadline))
        if hello.get("t") != "hello" or hello.get("protocol") != PROTOCOL_VERSION:
            refused = {
                "t": "refused",
                "type": "ProtocolError",
                "error": "unsupported protocol",
            }
            self._send(channel, refused)
            raise ProtocolError(f"refused hello: {hello.get('protocol')!r}")
        if self._refusal is not None:
            kind, message = self._refusal
            self._send(channel, {"t": "refused", "type": kind, "error": message})
            raise ConnectionError("store unavailable")
        self._send(
            channel,
            {
                "t": "welcome",
                "protocol": PROTOCOL_VERSION,
                "revision": self._identity.revision,
                "schema": self._identity.schema_version,
                "pid": os.getpid(),
            },
        )
        if hello.get("drain"):
            # A newer client needs a newer schema (ADR-1112 decision 6):
            # finish the open connections, accept none, exit.
            logger.info("draining at the request of a newer client")
            self._draining.set()
            raise ConnectionError("drain requested")
        return hello

    def _serve(self, channel: Any) -> None:
        label = self._peer_label(channel)
        try:
            hello = self._handshake(channel)
            client = f"{label} kind={hello.get('client')} rev={hello.get('revision')}"
            logger.info("connected %s", client)
            while not self._stopping.is_set():
                message = loads(channel.recv_frame(MAX_REQUEST_BYTES, None))
                self._touch()
                self._send(channel, self._answer(message, client))
                self._touch()
        except (ConnectionError, OSError, ProtocolError, TimeoutError) as exc:
            logger.info("closed %s: %s", label, type(exc).__name__)
        finally:
            channel.close()
            self._release()

    # ── requests ───────────────────────────────────────────────────────

    def _answer(self, message: dict[str, Any], client: str) -> dict[str, Any]:
        check_request(message)
        started = time.monotonic()
        task = Task(
            request_class=message["class"],
            deadline=started + float(message["deadline"]),
            run=lambda: self._execute(
                message["kind"],
                message["name"],
                message["args"],
                message["kwargs"],
                message["class"],
            ),
        )
        try:
            self._scheduler.submit(task)
            task.done.wait()
        except BaseException as exc:  # noqa: BLE001 — refusal returned to the requester
            task.error = exc
        outcome = "ok" if task.error is None else type(task.error).__name__
        logger.info(
            "req id=%s %s %s:%s class=%s executed=%s outcome=%s ms=%.1f",
            message["id"],
            client,
            message["kind"],
            message["name"],
            message["class"],
            task.executed,
            outcome,
            (time.monotonic() - started) * 1000.0,
        )
        if task.error is not None:
            error = {"type": type(task.error).__name__, "message": str(task.error)}
            return {"t": "res", "id": message["id"], "ok": False, "error": error}
        return {"t": "res", "id": message["id"], "ok": True, "v": task.result}

    # ── lifecycle ──────────────────────────────────────────────────────

    def _accept_loop(self) -> None:
        while not self._stopping.is_set():
            try:
                channel = self._accept()
            except OSError:
                if self._stopping.is_set():
                    return
                continue
            if channel is None:
                continue
            if self._draining.is_set() or not self._admit():
                logger.warning("refused a connection: %s open", self._connections)
                channel.close()
                continue
            threading.Thread(target=self._serve, args=(channel,), daemon=True).start()

    def _work(self) -> None:
        while (task := self._scheduler.take()) is not None:
            self._scheduler.execute(task)

    def _idle_for(self) -> float:
        with self._lock:
            if self._connections or not self._scheduler.idle():
                return 0.0
            if self._draining.is_set():
                return float("inf")
            return time.monotonic() - self._last_activity

    def run(self, close_listener: Callable[[], None]) -> None:
        """Serve until idle for ``idle_seconds`` (no connection, no work)."""
        workers = [
            threading.Thread(target=self._work, daemon=True)
            for _ in range(self._policy.scheduler.workers)
        ]
        for worker in workers:
            worker.start()
        threading.Thread(target=self._accept_loop, daemon=True).start()
        # source: ADR-1112 idle and drain are checked once a second
        while not self._stopping.wait(1.0):
            if self._idle_for() >= self._policy.idle_seconds:
                self._stopping.set()
        close_listener()
        self._scheduler.stop()
        for worker in workers:
            worker.join(timeout=self._policy.idle_seconds)

    def stop(self) -> None:
        self._stopping.set()

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            connections = self._connections
        return {"connections": connections, **self._scheduler.snapshot()}
