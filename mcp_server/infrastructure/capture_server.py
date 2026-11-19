"""Generic single-consumer capture worker with independent socket admission.

An admitted payload is a file in the journal before its acknowledgement, and the
file leaves only once the callback returned; the next worker replays what a dead
one left, and the callback's exact-replay dedup absorbs a store that ran twice.

source: ADR-0511 and ADR-1142"""

from __future__ import annotations

import asyncio
import queue
import socket
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from mcp_server.infrastructure import capture_spool
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
Entry = tuple[Payload, Path]


@dataclass(frozen=True)
class ServerPolicy:
    limits: Limits
    report: Report
    journal: (
        Path  # spool where an admitted payload is written before its ack (ADR-1142)
    )


class CaptureServer:
    def __init__(
        self, listener: socket.socket, callback: Callback, policy: ServerPolicy
    ):
        self.listener = listener
        self.callback = callback
        self.policy = policy
        # source: ADR-0511
        self.pending: queue.Queue[Entry | None] = queue.Queue(maxsize=1)
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
            self._admit(payload, deadline)
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

    def _admit(self, payload: Payload, deadline: float) -> None:
        """postcondition: the payload is queued and its journal file exists, or
        neither: a refused payload must not be replayed (the hook discards its
        artifact on a refusal, issue #737). source: ADR-1142"""
        timeout = remaining(deadline)  # an exhausted budget raises before the write
        path = capture_spool.write(self.policy.journal, payload)
        try:
            self.pending.put((payload, path), timeout=timeout)
        except queue.Full:
            path.unlink()
            raise

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
                "pending capture left in the journal for the next worker",
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

    def _next(self) -> Entry | None | Literal[False]:
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

    async def _replay(self, recovered: list[Path]) -> None:
        """Store what a dead worker left in the journal, each file at most once.

        A file is renamed before its replay: one still under that name at the
        next start killed the worker that replayed it, and is refused instead of
        killing every later worker. source: ADR-1142"""
        for path in capture_spool.interrupted_replays(self.policy.journal):
            failure = RuntimeError("the worker died replaying it")
            self._failed(path, failure, time.monotonic())
        for path in recovered:
            started = time.monotonic()
            try:
                path = capture_spool.claim_replay(path)
                payload = capture_spool.read(path)
            except (OSError, ValueError) as exc:
                self._failed(path, exc, started)
                continue
            await self._process(payload, path)

    async def _consume(self, recovered: list[Path]) -> None:
        await self._replay(recovered)
        while not self.stopping.is_set():
            entry = await asyncio.to_thread(self._next)
            if entry is None:
                return
            if entry is False:
                continue
            await self._process(*entry)

    async def _process(self, payload: Payload, path: Path) -> None:
        """postcondition: the journal file is gone once the callback returned, or
        renamed ``*.rejected`` and reported when it raised. source: ADR-1142"""
        started = time.monotonic()
        try:
            await self.callback(payload)
        except Exception as exc:  # noqa: BLE001 — composition callback boundary; failure is reported
            self._failed(path, exc, started)
            return
        try:
            path.unlink()
        except OSError as exc:
            self.policy.report(
                f"capture journal entry not removed, it will be replayed: {exc}",
                time.monotonic() - started,
                "capture_worker_lifecycle",
            )

    def _failed(self, path: Path, failure: Exception, started: float) -> None:
        """Retire a journal file that was not stored (``*.rejected``) and report it."""
        fate = "kept for inspection"
        try:
            capture_spool.reject(path)
        except OSError as exc:  # gone or unrenamable: the report still names it
            fate = f"left in place, rename failed: {exc}"
        self.policy.report(
            f"capture processing failed ({fate}): {type(failure).__name__}: {failure}",
            time.monotonic() - started,
            "capture_skipped",
        )

    def run(self) -> None:
        # Listed before the receiver starts, so only a dead worker's files are here.
        recovered = capture_spool.pending(self.policy.journal)
        capture_spool.sweep(self.policy.journal, time.time())
        receiver = threading.Thread(target=self._accept, daemon=True)
        receiver.start()
        try:
            asyncio.run(self._consume(recovered))
        finally:
            self.stopping.set()
            self.listener.close()
            receiver.join(timeout=self.policy.limits.timeout)
