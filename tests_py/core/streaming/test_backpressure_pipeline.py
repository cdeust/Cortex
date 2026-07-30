"""Tests for mcp_server.core.streaming.backpressure_pipeline.

Uses in-process fakes (no DB) to verify the pure orchestration contract:
correctness, shutdown without hangs, and failure isolation. The pytest suite
runs with a per-test timeout, so a broken shutdown protocol surfaces as a
timeout failure rather than an infinite hang.
"""

import threading
import time

import pytest

from mcp_server.core.streaming.backpressure_pipeline import (
    BackpressurePipeline,
    backpressure_pipeline_run,
    compute_queue_cap,
)


class FakeSource:
    """Yields ``n_batches`` batches of ``rows_per_batch`` ints, honoring max_batch."""

    def __init__(self, n_batches: int, rows_per_batch: int):
        self.n_batches = n_batches
        self.rows_per_batch = rows_per_batch

    def stream(self, max_batch: int):
        size = min(self.rows_per_batch, max_batch)
        for b in range(self.n_batches):
            yield list(range(b * size, b * size + size))


class RecordingSink:
    """Records every batch it writes; tracks peak concurrent queue occupancy."""

    def __init__(self, delay: float = 0.0):
        self.delay = delay
        self.written: list[list[int]] = []
        self.closed = False
        self._lock = threading.Lock()

    def write_batch(self, batch):
        if self.delay:
            time.sleep(self.delay)
        with self._lock:
            self.written.append(list(batch))
        return len(batch)

    def close(self):
        self.closed = True


class TestComputeQueueCap:
    def test_basic_formula(self):
        # 1_000_000 budget / (100 * 100) - 1 = 100 - 1 = 99
        assert compute_queue_cap(1_000_000, b_max=100, row_bytes=100, reserve=1) == 99

    def test_pinned_to_b_max_not_live_b(self):
        # A bigger b_max yields a SMALLER cap — the safety property: queue is
        # sized for the worst-case (largest) batch the controller can ramp to.
        small = compute_queue_cap(1_000_000, b_max=100, row_bytes=10)
        large = compute_queue_cap(1_000_000, b_max=10000, row_bytes=10)
        assert large < small

    def test_floors_at_one(self):
        assert compute_queue_cap(10, b_max=10000, row_bytes=1000) == 1

    @pytest.mark.parametrize("bad", [(-1, 10, 10), (10, 0, 10), (10, 10, 0)])
    def test_rejects_nonpositive(self, bad):
        with pytest.raises(ValueError):
            compute_queue_cap(bad[0], b_max=bad[1], row_bytes=bad[2])


class TestHappyPath:
    def test_all_rows_written_once(self):
        src = FakeSource(n_batches=10, rows_per_batch=50)
        sinks = []

        def factory():
            s = RecordingSink()
            sinks.append(s)
            return s

        pipe = BackpressurePipeline(
            source=src, sink_factory=factory, max_batch=50, queue_cap=4, concurrency=3
        )
        result = backpressure_pipeline_run(pipe)
        assert result.errors == []
        assert result.rows_in == 500
        assert result.rows_written == 500
        assert result.batches == 10
        # Every row delivered exactly once, no duplication / loss.
        all_rows = sorted(r for s in sinks for batch in s.written for r in batch)
        assert all_rows == list(range(500))
        assert all(s.closed for s in sinks)

    def test_one_worker_still_correct(self):
        src = FakeSource(n_batches=5, rows_per_batch=20)
        pipe = BackpressurePipeline(
            source=src,
            sink_factory=RecordingSink,
            max_batch=20,
            queue_cap=2,
            concurrency=1,
        )
        result = backpressure_pipeline_run(pipe)
        assert result.rows_written == 100
        assert result.errors == []


class TestBackpressure:
    def test_small_queue_slow_consumer_no_loss(self):
        # queue_cap=1, slow sink, fast producer: producer MUST block on put.
        # Correctness under maximal backpressure is the observable proof.
        src = FakeSource(n_batches=20, rows_per_batch=10)
        pipe = BackpressurePipeline(
            source=src,
            sink_factory=lambda: RecordingSink(delay=0.005),
            max_batch=10,
            queue_cap=1,
            concurrency=2,
        )
        result = backpressure_pipeline_run(pipe)
        assert result.rows_written == 200
        assert result.errors == []


class TestShutdownAndFailures:
    def test_producer_crash_releases_workers(self):
        class ExplodingSource:
            def stream(self, max_batch):
                yield [1, 2, 3]
                raise RuntimeError("kuzu boom")

        pipe = BackpressurePipeline(
            source=ExplodingSource(),
            sink_factory=RecordingSink,
            max_batch=10,
            queue_cap=2,
            concurrency=3,
        )
        result = backpressure_pipeline_run(pipe)  # must return, not hang
        assert any("producer" in e and "kuzu boom" in e for e in result.errors)

    def test_sink_setup_failure_no_hang(self):
        def bad_factory():
            raise RuntimeError("pool exhausted")

        pipe = BackpressurePipeline(
            source=FakeSource(3, 10),
            sink_factory=bad_factory,
            max_batch=10,
            queue_cap=2,
            concurrency=2,
        )
        result = backpressure_pipeline_run(pipe)  # must return despite no usable sinks
        assert any("worker-setup" in e for e in result.errors)
        assert len([e for e in result.errors if "worker-setup" in e]) == 2

    def test_write_failure_isolated_other_rows_survive(self):
        class FlakySink(RecordingSink):
            def write_batch(self, batch):
                if 0 in batch:  # only the first batch explodes
                    raise RuntimeError("write failed")
                return super().write_batch(batch)

        pipe = BackpressurePipeline(
            source=FakeSource(4, 10),
            sink_factory=FlakySink,
            max_batch=10,
            queue_cap=8,
            concurrency=1,
        )
        result = backpressure_pipeline_run(pipe)
        assert any("worker:" in e for e in result.errors)
        assert result.rows_written == 30  # 3 of 4 batches survived

    def test_close_failure_is_reported_not_swallowed(self):
        # issue #282 mutation-testing gap: no prior test made `.close()`
        # itself raise, so `_bp_close`'s error-reporting path (append to
        # result.errors under the lock) never ran — a mutant that appends
        # `None` instead of the formatted message, or drops the lock/result
        # arg entirely, was invisible.
        class CloseFailsSink(RecordingSink):
            def close(self):
                raise RuntimeError("disk full")

        pipe = BackpressurePipeline(
            source=FakeSource(2, 10),
            sink_factory=CloseFailsSink,
            max_batch=10,
            queue_cap=4,
            concurrency=1,
        )
        result = backpressure_pipeline_run(pipe)
        assert result.rows_written == 20  # writes still succeeded
        assert any("worker-close" in e and "disk full" in e for e in result.errors)
