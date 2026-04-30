"""Cortex telemetry — lightweight per-process counters for reads + writes.

Captures the empirical workload distribution (read/write ratio, latency
per op kind, cumulative byte-volume, success/failure split) so the
paper's "100x more reads than writes" claim is grounded in measurement,
not assertion (Popper C6).

Storage:
  * In-memory dict (per process) for fast snapshot/inspection.
  * Append-only JSONL at ~/.claude/methodology/telemetry.jsonl as the
    durable artifact for offline analysis. Restart-loss of the in-memory
    counters is acceptable because every call is captured in the JSONL.

Threading:
  Counter increments are guarded by a Lock so the MCP-thread + any
  background threads do not race on the running totals.

Opt-out:
  Set ``CORTEX_TELEMETRY_DISABLED=1`` in the environment to disable both
  the in-memory counters and the JSONL append.

Layer:
  Pure logic. No MCP, no DB, no embeddings. Filesystem write is local
  and best-effort (try/except OSError) so a full disk or permission
  error never propagates to the caller.

Contract (record):
  precondition: ``op`` is a non-empty string; ``latency_ms`` >= 0;
                byte / count fields are non-negative ints.
  postcondition: counters[op] is updated atomically; one JSONL line is
                appended on success or silently dropped on OSError; no
                exception escapes to the handler.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

_LOG_PATH = Path.home() / ".claude" / "methodology" / "telemetry.jsonl"
try:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
except OSError:
    # Directory creation may fail under sandbox; record() is still
    # safe -- the OSError on open() will be swallowed there too.
    pass

_lock = threading.Lock()
_counters: dict[str, dict[str, float | int]] = {}


def _disabled() -> bool:
    """source: opt-out contract documented in module docstring."""
    return os.environ.get("CORTEX_TELEMETRY_DISABLED") == "1"


def record(
    op: str,
    *,
    latency_ms: float,
    bytes_in: int = 0,
    bytes_out: int = 0,
    result_count: int = 0,
    ok: bool = True,
) -> None:
    """Record one operation.

    ``op`` is the canonical handler name, e.g. ``recall``, ``remember``,
    ``forget``, ``recall_hierarchical``. Cheap by design: one dict
    update + one short JSONL line. Target overhead < 1 ms (smoke-tested).
    """
    if _disabled():
        return
    record_line: dict[str, Any]
    with _lock:
        c = _counters.setdefault(
            op,
            {
                "count": 0,
                "ok": 0,
                "fail": 0,
                "bytes_in": 0,
                "bytes_out": 0,
                "result_count": 0,
                "latency_ms_sum": 0.0,
                "latency_ms_max": 0.0,
            },
        )
        c["count"] += 1
        c["ok" if ok else "fail"] += 1
        c["bytes_in"] += bytes_in
        c["bytes_out"] += bytes_out
        c["result_count"] += result_count
        c["latency_ms_sum"] += latency_ms
        if latency_ms > c["latency_ms_max"]:
            c["latency_ms_max"] = latency_ms
        record_line = {
            "ts": time.time(),
            "op": op,
            "latency_ms": round(latency_ms, 3),
            "bytes_in": bytes_in,
            "bytes_out": bytes_out,
            "result_count": result_count,
            "ok": ok,
        }
    # JSONL append is best-effort: a full disk or permission error must
    # never break the handler. The in-memory counters are already updated.
    try:
        with _LOG_PATH.open("a") as f:
            f.write(json.dumps(record_line) + "\n")
    except OSError:
        pass


def snapshot() -> dict[str, dict[str, float | int]]:
    """Return a deep-enough copy of the current counters for inspection."""
    with _lock:
        return {op: dict(c) for op, c in _counters.items()}


_READ_OPS = {
    "recall",
    "recall_hierarchical",
    "navigate_memory",
    "get_causal_chain",
    "drill_down",
}
_WRITE_OPS = {"remember", "forget", "validate_memory", "rate_memory"}


def ratio_reads_writes(snap: dict[str, dict[str, float | int]] | None = None) -> float:
    """Compute reads / max(writes, 1) over the current counters.

    Reads = the canonical retrieval ops; writes = mutations + curation.
    The denominator is clamped so a fresh process returns 0.0 instead
    of dividing by zero.
    """
    s = snap if snap is not None else snapshot()
    reads = sum(int(c["count"]) for op, c in s.items() if op in _READ_OPS)
    writes = sum(int(c["count"]) for op, c in s.items() if op in _WRITE_OPS)
    return reads / max(writes, 1)


def reset() -> None:
    """Wipe the in-memory counters. The on-disk JSONL is not touched."""
    with _lock:
        _counters.clear()


def summary() -> dict[str, Any]:
    """Snapshot + computed read/write ratio + per-op average latency."""
    snap = snapshot()
    derived: dict[str, dict[str, float]] = {}
    for op, c in snap.items():
        count = max(int(c["count"]), 1)
        derived[op] = {
            "avg_latency_ms": round(float(c["latency_ms_sum"]) / count, 3),
            "max_latency_ms": round(float(c["latency_ms_max"]), 3),
        }
    return {
        "counters": snap,
        "derived": derived,
        "ratio_reads_writes": round(ratio_reads_writes(snap), 3),
        "log_path": str(_LOG_PATH),
        "disabled": _disabled(),
    }
