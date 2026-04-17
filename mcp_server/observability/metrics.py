"""Phase 7 observability: Prometheus metrics without the prometheus_client dep.

We emit the text-exposition format (Prometheus 0.0.4 spec) directly.
Adding prometheus_client as a dependency was rejected because it pulls
in a runtime server on port 9090 by default, which conflicts with
Cortex's single-port MCP stdio transport. Our emitter is ~60 lines,
covers the subset of metric types we actually need (counter, histogram,
gauge), and is testable without a scrape loop.

Metrics exposed:
  cortex_tool_calls_total{tool, status}
    Counter — successful vs failed tool calls per tool name.

  cortex_tool_duration_seconds{tool}
    Histogram — per-tool call latency (buckets: 0.01, 0.05, 0.1, 0.5, 1,
    5, 10, 30, 60, +Inf). Wired from safe_handler.

  cortex_memories_total
    Gauge — current memory count (scraped from SELECT COUNT(*)).

  cortex_pool_checkouts_total{pool}
    Counter — successful connection acquisitions per pool.

  cortex_pool_timeouts_total{pool}
    Counter — acquisition timeouts per pool.

Source:
  * Prometheus text format 0.0.4:
    https://prometheus.io/docs/instrumenting/exposition_formats/
  * docs/program/phase-5-pool-admission-design.md §7.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict

_LOCK = threading.Lock()

# Histograms — per-tool bucket tallies. Upper bounds in seconds.
_BUCKETS = (0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0)

# Counters keyed by (metric_name, labels_tuple) → int
_counters: dict[tuple, int] = defaultdict(int)
# Gauges keyed by (metric_name, labels_tuple) → float (last-set value)
_gauges: dict[tuple, float] = {}
# Histogram buckets: (metric_name, labels_tuple, upper_bound) → count
_hist_buckets: dict[tuple, int] = defaultdict(int)
# Histogram sums: (metric_name, labels_tuple) → sum-of-observations
_hist_sums: dict[tuple, float] = defaultdict(float)


def _labels_tuple(labels: dict | None) -> tuple:
    if not labels:
        return ()
    return tuple(sorted(labels.items()))


def inc_counter(name: str, labels: dict | None = None, value: int = 1) -> None:
    """Increment a counter by ``value`` (default 1)."""
    with _LOCK:
        _counters[(name, _labels_tuple(labels))] += value


def set_gauge(name: str, value: float, labels: dict | None = None) -> None:
    """Set a gauge to the given value."""
    with _LOCK:
        _gauges[(name, _labels_tuple(labels))] = float(value)


def observe_histogram(
    name: str,
    value_seconds: float,
    labels: dict | None = None,
) -> None:
    """Record one observation into the histogram for ``name``."""
    lt = _labels_tuple(labels)
    with _LOCK:
        _hist_sums[(name, lt)] += value_seconds
        for b in _BUCKETS:
            if value_seconds <= b:
                _hist_buckets[(name, lt, b)] += 1
        _hist_buckets[(name, lt, float("inf"))] += 1


class Timer:
    """Context manager that observes elapsed wall time into a histogram."""

    def __init__(self, name: str, labels: dict | None = None) -> None:
        self._name = name
        self._labels = labels
        self._t0 = 0.0

    def __enter__(self) -> "Timer":
        self._t0 = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        observe_histogram(self._name, time.monotonic() - self._t0, self._labels)


# ── Exposition ───────────────────────────────────────────────────────────


def _render_labels(lt: tuple) -> str:
    if not lt:
        return ""
    body = ",".join(f'{k}="{v}"' for k, v in lt)
    return "{" + body + "}"


def render() -> str:
    """Render all metrics in Prometheus text format 0.0.4.

    Returns a string suitable for writing to an HTTP response whose
    Content-Type is ``text/plain; version=0.0.4; charset=utf-8``.
    """
    lines: list[str] = []
    with _LOCK:
        # Counters
        counter_names = sorted({name for (name, _) in _counters})
        for name in counter_names:
            lines.append(f"# TYPE {name} counter")
            for (n, lt), v in sorted(_counters.items()):
                if n == name:
                    lines.append(f"{name}{_render_labels(lt)} {v}")
        # Gauges
        gauge_names = sorted({name for (name, _) in _gauges})
        for name in gauge_names:
            lines.append(f"# TYPE {name} gauge")
            for (n, lt), v in sorted(_gauges.items()):
                if n == name:
                    lines.append(f"{name}{_render_labels(lt)} {v}")
        # Histograms
        hist_names = sorted({name for (name, _, _) in _hist_buckets})
        for name in hist_names:
            lines.append(f"# TYPE {name} histogram")
            # Emit buckets per label-set in ascending upper-bound order
            label_sets = sorted(
                {lt for (n, lt, _) in _hist_buckets if n == name}
            )
            for lt in label_sets:
                # Cumulative counts (Prometheus wants cumulative, and our
                # observe_histogram already sums up; re-assert le order).
                for b in list(_BUCKETS) + [float("inf")]:
                    count = _hist_buckets.get((name, lt, b), 0)
                    le = "+Inf" if b == float("inf") else f"{b}"
                    bucket_labels = dict(lt) if lt else {}
                    bucket_labels["le"] = le
                    lines.append(
                        f"{name}_bucket{_render_labels(_labels_tuple(bucket_labels))} {count}"
                    )
                lines.append(
                    f"{name}_sum{_render_labels(lt)} {_hist_sums.get((name, lt), 0.0)}"
                )
                total = _hist_buckets.get((name, lt, float("inf")), 0)
                lines.append(f"{name}_count{_render_labels(lt)} {total}")
    lines.append("")  # trailing newline per Prometheus spec
    return "\n".join(lines)


def reset() -> None:
    """Drop all metrics. For tests only."""
    with _LOCK:
        _counters.clear()
        _gauges.clear()
        _hist_buckets.clear()
        _hist_sums.clear()
