"""Adaptive batch writer + drain — AIMD-sized, load-balanced, backpressured.

Pairs an ``AdaptiveBatchController`` (AIMD batch sizing from observed write
latency) with a ``BatchSink``, and fans rows across N such writers behind a
bounded queue:

  - **Adaptive sizing** — each writer grows its batch while writes stay under
    the latency target and halves it when PG slows (AIMD; Jacobson 1988,
    Chiu & Jain 1989). The calibration sweep showed edge throughput rising 6x
    from 1k→10k rows/batch, so a fixed size leaves throughput on the table.
  - **Load balancing** — a bounded thread-safe queue hands each page to
    whichever of ``concurrency`` workers is free; under PG contention every
    worker's controller shrinks together, converging to a fair share (the same
    AIMD fairness property), so writers self-balance with no central scheduler.
  - **Backpressure** — the queue is bounded; a full queue blocks the producer
    (SEDA; Welsh 2001), so the async page-fetcher pauses instead of piling up.

Pure orchestration — depends only on the sink / controller abstractions.
"""

from __future__ import annotations

import asyncio
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable

from mcp_server.core.streaming.adaptive_controller import (
    AdaptiveBatchController,
    adaptive_batch_controller_batch_size,
    adaptive_batch_controller_observe,
)
from mcp_server.core.streaming.ports import BatchSink


def compute_queue_cap(
    ram_budget_bytes: int, b_max: int, row_bytes: int, reserve: int = 1
) -> int:
    """``Q_cap = floor(RAM_budget / (b_max * row_bytes)) - reserve``.

    Pinned to ``b_max`` (NOT the live B): the controller ramps B up to b_max,
    so sizing from a smaller live B would let peak RAM overshoot once it ramps.
    source: Little (1961), occupancy bound applied to memory. Floors at 1.
    """
    if b_max <= 0 or row_bytes <= 0:
        raise ValueError("b_max and row_bytes must be positive")
    if ram_budget_bytes <= 0:
        raise ValueError("ram_budget_bytes must be positive")
    return max(1, ram_budget_bytes // (b_max * row_bytes) - reserve)


class AdaptiveBatchWriter:
    """Buffers rows; flushes controller-sized batches; feeds latency back.

    One writer is single-threaded (its sink owns one connection). The buffer
    holds at most ``b_max + one input page`` rows, so peak RAM stays bounded.
    """

    def __init__(self, sink: BatchSink, controller: AdaptiveBatchController):
        self._sink = sink
        self._controller = controller
        self._buf: list[Any] = []
        self.rows_written = 0

    def add_many(self, rows: list[Any]) -> None:
        """Append rows; flush as many controller-sized batches as are ready."""
        self._buf.extend(rows)
        while len(self._buf) >= adaptive_batch_controller_batch_size(self._controller):
            n = adaptive_batch_controller_batch_size(self._controller)
            self._flush(self._buf[:n])
            del self._buf[:n]

    def flush_remaining(self) -> None:
        """Flush the buffered tail (a final, possibly smaller, batch)."""
        if self._buf:
            self._flush(self._buf)
            self._buf = []

    def _flush(self, batch: list[Any]) -> None:
        t0 = time.perf_counter()
        written = self._sink.write_batch(batch)
        adaptive_batch_controller_observe(
            self._controller, time.perf_counter() - t0
        )  # AIMD step
        self.rows_written += written


@dataclass
class DrainResult:
    rows_written: int = 0
    errors: list[str] = field(default_factory=list)


class _Sentinel:
    """Poison pill — one per worker to signal end-of-stream."""


_SENTINEL = _Sentinel()


async def adaptive_drain(
    pages: AsyncIterator[list[Any]],
    sink_factory: Callable[[], BatchSink],
    controller_factory: Callable[[], AdaptiveBatchController],
    *,
    concurrency: int = 2,
    queue_cap: int = 8,
) -> DrainResult:
    """Drain an async page iterator into N adaptive, load-balanced writers.

    The async producer (e.g. a Kuzu pager) stays on the event loop; each page
    is offloaded onto a bounded queue via ``asyncio.to_thread(q.put, ...)`` —
    which blocks (backpressure) when the queue is full while keeping the loop
    free to fetch the next page (producer || consumer overlap). ``concurrency``
    worker threads each run an ``AdaptiveBatchWriter`` with its own sink + AIMD
    controller. One sentinel per worker (emitted in ``finally``, so a producer
    crash still releases every worker) ends the run; workers flush their tail
    and close. Returns total rows written + any surfaced errors.
    """
    q: queue.Queue[Any] = queue.Queue(maxsize=queue_cap)
    result = DrainResult()
    lock = threading.Lock()
    workers = [
        threading.Thread(
            target=_drain_worker,
            args=(q, sink_factory, controller_factory, result, lock),
            name=f"adaptive-writer-{i}",
        )
        for i in range(concurrency)
    ]
    for w in workers:
        w.start()
    try:
        async for rows in pages:
            if rows:
                await asyncio.to_thread(q.put, rows)  # blocks when full
    except Exception as exc:  # noqa: BLE001 — surfaced via result
        with lock:
            result.errors.append(f"producer: {exc!r}")
    finally:
        for _ in range(concurrency):
            await asyncio.to_thread(q.put, _SENTINEL)
    await asyncio.to_thread(lambda: [w.join() for w in workers])
    return result


def _drain_worker(
    q: "queue.Queue[Any]",
    sink_factory: Callable[[], BatchSink],
    controller_factory: Callable[[], AdaptiveBatchController],
    result: DrainResult,
    lock: threading.Lock,
) -> None:
    sink = _build(sink_factory, result, lock)
    if sink is None:
        _drain_to_sentinel(q)
        return
    writer = AdaptiveBatchWriter(sink, controller_factory())
    try:
        while True:
            item = q.get()
            if item is _SENTINEL:
                break
            _safe(lambda: writer.add_many(item), "worker", result, lock)
        _safe(writer.flush_remaining, "worker-flush", result, lock)
    finally:
        with lock:
            result.rows_written += writer.rows_written
        _safe(sink.close, "worker-close", result, lock)


def _build(sink_factory, result: DrainResult, lock: threading.Lock):
    try:
        return sink_factory()
    except Exception as exc:  # noqa: BLE001
        with lock:
            result.errors.append(f"worker-setup: {exc!r}")
        return None


def _drain_to_sentinel(q: "queue.Queue[Any]") -> None:
    while q.get() is not _SENTINEL:
        pass


def _safe(fn, label: str, result: DrainResult, lock: threading.Lock) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        with lock:
            result.errors.append(f"{label}: {exc!r}")
