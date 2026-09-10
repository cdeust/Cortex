"""Generic single-consumer capture worker with independent socket admission.

source: ADR-0511"""

from __future__ import annotations

import asyncio
import queue
import socket
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from mcp_server.infrastructure.capture_peer import authenticate
from mcp_server.infrastructure.capture_transport import (
    CaptureTransportError,
    Limits,
    acknowledge,
    receive,
    remaining,
)

Payload = dict[str, object]
Callback = Callable[[Payload], Awaitable[None]]
Report = Callable[[str, float, str], None]


@dataclass(frozen=True)
class ServerPolicy:
    limits: Limits
    report: Report


class CaptureServer:
    def __init__(
        self, listener: socket.socket, callback: Callback, policy: ServerPolicy
    ):
        self.listener = listener
        self.callback = callback
        self.policy = policy
        # source: ADR-0511
        self.pending: queue.Queue[Payload | None] = queue.Queue(maxsize=1)
        self.stopping = threading.Event()
        self.admission = threading.Lock()
        self.receiving = False

    def _receive(self, connection: socket.socket) -> None:
        started = time.monotonic()
        deadline = started + self.policy.limits.timeout
        connection.settimeout(self.policy.limits.timeout)
        try:
            authenticate(connection)
            payload = receive(connection, self.policy.limits.max_bytes, deadline)
            self.pending.put(payload, timeout=remaining(deadline))
            connection.settimeout(remaining(deadline))
            acknowledge(connection, True)
        except (OSError, CaptureTransportError, queue.Full) as exc:
            self.policy.report(
                f"capture admission failed: {type(exc).__name__}: {exc}",
                time.monotonic() - started,
                "capture_skipped",
            )
            rejection_started = time.monotonic()
            try:
                acknowledge(connection, False)
            except OSError as failure:
                self.policy.report(
                    f"capture rejection delivery failed: {failure}",
                    time.monotonic() - rejection_started,
                    "capture_worker_lifecycle",
                )

    def _accept(self) -> None:
        self.listener.settimeout(
            min(self.policy.limits.timeout, self.policy.limits.idle)
        )
        while not self.stopping.is_set():
            started = time.monotonic()
            try:
                connection, _ = self.listener.accept()
            except TimeoutError:
                continue  # Poll only the shutdown flag, using the transport budget.
            except OSError as exc:
                if not self.stopping.is_set():
                    self._listener_failed(exc, time.monotonic() - started)
                return
            with connection:
                self._handle(connection)

    def _listener_failed(self, failure: OSError, elapsed: float) -> None:
        self.policy.report(
            f"capture listener failed: {failure}", elapsed, "capture_worker_lifecycle"
        )
        self.stopping.set()
        started = time.monotonic()
        try:
            self.pending.put_nowait(None)  # Wake an idle consumer immediately.
        except queue.Full:
            self.policy.report(
                "pending capture abandoned after listener failure",
                time.monotonic() - started,
                "capture_worker_lifecycle",
            )

    def _handle(self, connection: socket.socket) -> None:
        with self.admission:
            if self.stopping.is_set():
                return
            self.receiving = True
        try:
            self._receive(connection)
        finally:
            with self.admission:
                self.receiving = False

    def _next(self) -> Payload | None | Literal[False]:
        try:
            return self.pending.get(timeout=self.policy.limits.idle)
        except queue.Empty:
            with self.admission:
                if self.receiving or not self.pending.empty():
                    return (
                        False  # Admission activity resets the idle wait, no inference.
                    )
                self.stopping.set()
            return None

    async def _consume(self) -> None:
        while not self.stopping.is_set():
            payload = await asyncio.to_thread(self._next)
            if payload is None:
                return
            if payload is False:
                continue
            started = time.monotonic()
            try:
                await self.callback(payload)
            except Exception as exc:  # noqa: BLE001 — composition callback boundary; failure is reported
                self.policy.report(
                    f"capture processing failed: {type(exc).__name__}: {exc}",
                    time.monotonic() - started,
                    "capture_skipped",
                )

    def run(self) -> None:
        receiver = threading.Thread(target=self._accept, daemon=True)
        receiver.start()
        try:
            asyncio.run(self._consume())
        finally:
            self.stopping.set()
            self.listener.close()
            receiver.join(timeout=self.policy.limits.timeout)
