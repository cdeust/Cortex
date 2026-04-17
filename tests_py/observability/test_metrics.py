"""Phase 7 observability: Prometheus text-format emitter tests.

Asserts:
  * counter / gauge / histogram APIs work
  * render() produces valid Prometheus 0.0.4 text format
  * thread-safe under concurrent increments
  * reset() drops all state (isolation between tests)

Source: docs/program/phase-5-pool-admission-design.md §7 (hardening).
"""

from __future__ import annotations

import threading
import time

import pytest

from mcp_server.observability import metrics


@pytest.fixture(autouse=True)
def _clean_state():
    metrics.reset()
    yield
    metrics.reset()


class TestCounter:
    def test_increment_default(self):
        metrics.inc_counter("cortex_tool_calls_total", {"tool": "recall"})
        out = metrics.render()
        assert (
            'cortex_tool_calls_total{tool="recall"} 1' in out
        )

    def test_increment_multiple(self):
        metrics.inc_counter("cortex_tool_calls_total", {"tool": "recall"})
        metrics.inc_counter("cortex_tool_calls_total", {"tool": "recall"})
        metrics.inc_counter("cortex_tool_calls_total", {"tool": "recall"}, value=3)
        out = metrics.render()
        assert 'cortex_tool_calls_total{tool="recall"} 5' in out

    def test_different_label_sets_independent(self):
        metrics.inc_counter("calls", {"tool": "recall"})
        metrics.inc_counter("calls", {"tool": "remember"})
        out = metrics.render()
        assert 'calls{tool="recall"} 1' in out
        assert 'calls{tool="remember"} 1' in out


class TestGauge:
    def test_set_replaces(self):
        metrics.set_gauge("cortex_memories_total", 100)
        metrics.set_gauge("cortex_memories_total", 200)
        out = metrics.render()
        assert "cortex_memories_total 200" in out

    def test_gauge_with_labels(self):
        metrics.set_gauge("pool_size", 2.0, {"pool": "interactive"})
        out = metrics.render()
        assert 'pool_size{pool="interactive"} 2.0' in out


class TestHistogram:
    def test_observe_populates_buckets(self):
        metrics.observe_histogram("cortex_tool_duration_seconds", 0.05)
        out = metrics.render()
        # 0.05 falls into le=0.05 and above
        assert (
            'cortex_tool_duration_seconds_bucket{le="0.05"} 1' in out
        )
        assert (
            'cortex_tool_duration_seconds_bucket{le="+Inf"} 1' in out
        )
        assert "cortex_tool_duration_seconds_count 1" in out

    def test_observe_accumulates_sum(self):
        metrics.observe_histogram("d", 0.1)
        metrics.observe_histogram("d", 0.2)
        out = metrics.render()
        assert "d_sum 0.3" in out or "d_sum 0.30" in out
        assert "d_count 2" in out

    def test_timer_context_manager(self):
        with metrics.Timer("cortex_tool_duration_seconds", {"tool": "recall"}):
            time.sleep(0.001)
        out = metrics.render()
        assert 'cortex_tool_duration_seconds_count{tool="recall"} 1' in out


class TestThreadSafety:
    def test_concurrent_increments(self):
        N_THREADS = 16
        N_INCREMENTS = 100

        def worker():
            for _ in range(N_INCREMENTS):
                metrics.inc_counter("concurrent")

        threads = [threading.Thread(target=worker) for _ in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        out = metrics.render()
        expected = N_THREADS * N_INCREMENTS
        assert f"concurrent {expected}" in out


class TestRenderFormat:
    def test_type_line_per_metric(self):
        metrics.inc_counter("foo")
        metrics.set_gauge("bar", 1.0)
        out = metrics.render()
        assert "# TYPE foo counter" in out
        assert "# TYPE bar gauge" in out

    def test_trailing_newline(self):
        metrics.inc_counter("x")
        out = metrics.render()
        assert out.endswith("\n")
