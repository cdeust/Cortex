"""Calibrated streaming constants — MEASURED, not invented.

source: benchmark benchmarks/streaming_calibration/run.py, measured 2026-06-04
on local PostgreSQL 15 (cortex_test). These are PROPERTIES OF THE PG INSTANCE
(schema, indexes, hardware), not portable constants — re-run the sweep and
update them when the environment changes (Kleinrock 1975: B_min/B_max are
instance properties). Provenance for every number is the committed
``benchmarks/streaming_calibration/results.json``.

Sweep (p99 write latency / throughput vs batch size):
  entity: peak 73k rows/s @ 5000 (p99 111 ms); throughput drops past 5000.
  edge:   peak 221k rows/s @ 10000 (p99 131 ms) — 6x the 1000-row rate, which
          is exactly why fixed sizing is wrong and AIMD is justified.
"""

from __future__ import annotations

from mcp_server.core.streaming.adaptive_controller import AdaptiveBatchController
from mcp_server.core.streaming.queue_sizing import compute_queue_cap

# RAM budget for in-flight write buffers per ingest phase. Conservative — the
# bounded queue + per-worker buffers stay far under this (a few MB in practice).
WRITE_RAM_BUDGET_BYTES = 256 * 1024 * 1024

# Entity staging path (COPY → INSERT … SELECT … WHERE NOT EXISTS).
ENTITY_B_MIN = 500
ENTITY_B_MAX = 5000
ENTITY_W_TARGET_S = 0.111
ENTITY_ROW_BYTES = 213

# Edge staging path (COPY → INSERT … JOIN entities … ON CONFLICT DO NOTHING).
EDGE_B_MIN = 1000
EDGE_B_MAX = 10000
EDGE_W_TARGET_S = 0.131
EDGE_ROW_BYTES = 206

# Hard ceiling on the bounded queue regardless of budget — small queues give
# tighter backpressure; the budget only ever *lowers* this.
_MAX_QUEUE_CAP = 8


def make_entity_controller() -> AdaptiveBatchController:
    """AIMD controller for the entity stage (measured bounds)."""
    return AdaptiveBatchController(ENTITY_B_MIN, ENTITY_B_MAX, ENTITY_W_TARGET_S)


def make_edge_controller() -> AdaptiveBatchController:
    """AIMD controller for the edge stage (measured bounds)."""
    return AdaptiveBatchController(EDGE_B_MIN, EDGE_B_MAX, EDGE_W_TARGET_S)


def entity_queue_cap() -> int:
    return min(
        _MAX_QUEUE_CAP,
        compute_queue_cap(WRITE_RAM_BUDGET_BYTES, ENTITY_B_MAX, ENTITY_ROW_BYTES),
    )


def edge_queue_cap() -> int:
    return min(
        _MAX_QUEUE_CAP,
        compute_queue_cap(WRITE_RAM_BUDGET_BYTES, EDGE_B_MAX, EDGE_ROW_BYTES),
    )
