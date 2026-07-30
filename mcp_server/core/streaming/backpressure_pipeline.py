"""Backpressure pipeline — bounded-queue producer/consumer with constant peak RAM.

Pure orchestration logic — depends only on the StreamSource / BatchSink ports
(DIP); does no I/O itself. The injected sinks perform the writes.

Topology: one producer thread drains a StreamSource into a bounded queue;
``concurrency`` worker threads pull batches and call ``BatchSink.write_batch``.
The bounded queue with blocking ``put`` IS the backpressure mechanism (SEDA,
Welsh et al. 2001): when writers fall behind, the queue fills, the producer
blocks, and the source stops fetching. Peak resident payload is
``(queue_cap + concurrency + 1)`` batches — independent of total row count.

Shutdown: the producer emits exactly one sentinel per worker in a ``finally``
(so it fires on the crash path too); each worker consumes exactly one sentinel
and stops; the caller joins all workers before any pool is closed. There is no
other end-of-stream signal in the codebase, so this protocol is load-bearing.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from mcp_server.core.streaming.ports import BatchSink, StreamSource


@dataclass
class PipelineResult:
    """Outcome of one pipeline run (mutated under a lock by all threads)."""

    rows_in: int = 0
    rows_written: int = 0
    batches: int = 0
    errors: list[str] = field(default_factory=list)


class _Sentinel:
    """Poison pill — one is enqueued per worker to signal end-of-stream."""


_SENTINEL = _Sentinel()


def compute_queue_cap(
    ram_budget_bytes: int, b_max: int, row_bytes: int, reserve: int = 1
) -> int:
    """``Q_cap = floor(RAM_budget / (b_max * row_bytes)) - reserve``.

    Pinned to ``b_max`` (NOT the live B): the controller ramps B up to b_max,
    so sizing from a smaller live B would let peak RAM overshoot the budget by
    ``b_max / B`` once it ramps. source: Little (1961), occupancy bound applied
    to memory rather than time. Floors at 1 so the pipeline always makes
    progress.
    """
    if b_max <= 0 or row_bytes <= 0:
        raise ValueError("b_max and row_bytes must be positive")
    if ram_budget_bytes <= 0:
        raise ValueError("ram_budget_bytes must be positive")
    cap = ram_budget_bytes // (b_max * row_bytes) - reserve
    return max(1, cap)


@dataclass
class BackpressurePipeline:
    """Runs ``source -> bounded queue -> c x sink`` with bounded peak RAM.

    ``sink_factory`` builds ONE sink per worker — each worker owns its own
    connection (sharing a connection across threads is unsafe). The factory is
    injected by the handler (composition root) and binds the appropriate pool.

    Data only — deliberately no methods. mutmut's mutation generator
    categorically excludes the body of any `@dataclass`-decorated class
    (`mutmut/mutation/file_mutation.py:236`) — including `@staticmethod`
    members, since the exclusion fires on the decorated `ClassDef` itself,
    before the per-method `@staticmethod` exception is ever consulted — so
    logic placed on methods here would carry zero mutation coverage no
    matter how the test loader names the module (issue #262 3rd pass;
    issue #282). `backpressure_pipeline_run` (the public entry point) plus
    the private `_bp_produce` / `_bp_consume` / `_bp_build_sink` /
    `_bp_write_one` / `_bp_close` helpers below carry the same logic as
    free functions instead.
    """

    source: StreamSource
    sink_factory: Callable[[], BatchSink]
    max_batch: int
    queue_cap: int
    concurrency: int = 2


def backpressure_pipeline_run(pipeline: "BackpressurePipeline") -> PipelineResult:
    """Drain the source through the workers; block until fully flushed.

    Postcondition: on return, every row the source yielded has been handed
    to a sink and durably committed (the staged barrier later phases rely
    on) OR surfaced in ``result.errors``.
    """
    q: queue.Queue[Any] = queue.Queue(maxsize=pipeline.queue_cap)
    result = PipelineResult()
    lock = threading.Lock()
    # §12 note: the `name=` kwargs below (both threads) are debug-only
    # labels (visible via `threading.enumerate()` / crash dumps) — they do
    # not affect the returned PipelineResult, the only contract this
    # function's tests assert against, so a mutant that changes, drops, or
    # nulls a thread's `name` is EQUIVALENT for that contract. Verified
    # empirically: mutating `name=` never changed a test outcome across the
    # full `_bp_*` mutation sweep (issue #282).
    producer = threading.Thread(
        target=_bp_produce, args=(pipeline, q, result, lock), name="bp-producer"
    )
    workers = [
        threading.Thread(
            target=_bp_consume, args=(pipeline, q, result, lock), name=f"bp-worker-{i}"
        )
        for i in range(pipeline.concurrency)
    ]
    producer.start()
    for w in workers:
        w.start()
    producer.join()
    for w in workers:
        w.join()
    return result


def _bp_produce(
    pipeline: "BackpressurePipeline",
    q: "queue.Queue[Any]",
    result: PipelineResult,
    lock: threading.Lock,
) -> None:
    try:
        for batch in pipeline.source.stream(pipeline.max_batch):
            q.put(batch)  # blocks when full — this is the backpressure
            with lock:
                result.rows_in += len(batch)
                result.batches += 1
    except Exception as exc:  # noqa: BLE001 — surfaced via result, not raised
        with lock:
            result.errors.append(f"producer: {exc!r}")
    finally:
        # Exactly one sentinel per worker — in finally so a producer crash
        # still releases every worker (no hang on an empty-but-open queue).
        for _ in range(pipeline.concurrency):
            q.put(_SENTINEL)


def _bp_consume(
    pipeline: "BackpressurePipeline",
    q: "queue.Queue[Any]",
    result: PipelineResult,
    lock: threading.Lock,
) -> None:
    sink = _bp_build_sink(pipeline, result, lock)
    try:
        while True:
            item = q.get()
            if item is _SENTINEL:
                return  # consumed our one sentinel — stop
            if sink is None:
                continue  # setup failed; drain to our sentinel, don't hang
            _bp_write_one(sink, item, result, lock)
    finally:
        if sink is not None:
            _bp_close(sink, result, lock)


def _bp_build_sink(
    pipeline: "BackpressurePipeline", result: PipelineResult, lock: threading.Lock
) -> BatchSink | None:
    try:
        return pipeline.sink_factory()
    except Exception as exc:  # noqa: BLE001
        with lock:
            result.errors.append(f"worker-setup: {exc!r}")
        return None


def _bp_write_one(
    sink: BatchSink,
    item: list[Any],
    result: PipelineResult,
    lock: threading.Lock,
) -> None:
    try:
        written = sink.write_batch(item)
        with lock:
            result.rows_written += written
    except Exception as exc:  # noqa: BLE001
        with lock:
            result.errors.append(f"worker: {exc!r}")


def _bp_close(sink: BatchSink, result: PipelineResult, lock: threading.Lock) -> None:
    try:
        sink.close()
    except Exception as exc:  # noqa: BLE001
        with lock:
            result.errors.append(f"worker-close: {exc!r}")
