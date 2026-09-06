"""Cortex telemetry — lightweight per-process counters for reads + writes.

Captures the empirical workload distribution (read/write ratio, latency
per op kind, cumulative byte-volume, success/failure split) so the
paper's "100x more reads than writes" claim is grounded in measurement,
not assertion (Popper C6).

Storage:
  * In-memory dict (per process) for fast snapshot/inspection.
  * Size-rotated JSONL at ~/.claude/methodology/telemetry.jsonl, with one
    previous segment (.1) for offline analysis. In-memory counters span the
    process lifetime; the files retain only the current and previous segments.

Threading:
  Counter increments are guarded by a Lock so the MCP-thread + any
  background threads do not race on the running totals.

Opt-out:
  Set ``CORTEX_TELEMETRY_DISABLED=1`` in the environment to disable both
  the in-memory counters and the JSONL append.

Optional export (issue #122):
  ``TelemetryExporter`` is a port (Protocol) that outer layers may
  implement to mirror each recorded sample onto an external sink (e.g.
  OTLP). Core declares the port only -- it never imports an exporter
  implementation. The composition root (mcp_server/__main__.py) wires a
  concrete exporter via ``set_exporter()`` at startup, OFF by default
  (``set_exporter`` is never called unless the operator opted in via
  env var -- see infrastructure/otel_exporter.py::build_otel_exporter).
  Export is best-effort: any exception raised by the exporter is caught
  here and never propagates to the caller, same guarantee as the JSONL
  append below.

Layer:
  Pure logic. No MCP, no DB, no embeddings. Filesystem write is local
  and best-effort (try/except OSError) so a full disk or permission
  error never propagates to the caller.

Contract (record):
  precondition: ``op`` is a non-empty string; ``latency_ms`` >= 0;
                byte / count fields are non-negative ints.
  postcondition: a sample is published immediately, or captured until the
                MCP response exists. Publication updates counters atomically
                and writes JSONL/exporter best-effort, without failing callers.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, TypedDict, runtime_checkable

from mcp_server.shared.telemetry_context import retrieval_metrics
from mcp_server.shared.log_rotation import open_rotating_log

logger = logging.getLogger(__name__)


@runtime_checkable
class TelemetryExporter(Protocol):
    """Port for mirroring recorded samples onto an external sink.

    Contract:
      - ``export`` receives the same dict shape written to the JSONL log
        (``ts``, ``op``, ``latency_ms``, ``bytes_in``, ``bytes_out``,
        ``result_count``, ``ok``, ``tier``, ``reranked_count``).
      - ``export`` MUST NOT raise for control flow that reaches the
        caller -- ``record()`` catches any exception defensively, but a
        well-behaved implementation handles its own I/O errors.
    """

    def export(self, sample: dict[str, Any]) -> None:
        """Mirror one recorded sample onto the external sink."""
        ...


_exporter: TelemetryExporter | None = None


def set_exporter(exporter: TelemetryExporter | None) -> None:
    """Register (or clear, with ``None``) the optional telemetry exporter.

    precondition: none (``exporter`` may be ``None`` to disable export).
    postcondition: subsequent ``record()`` calls invoke
                   ``exporter.export(sample)`` best-effort; the local
                   in-memory counters and JSONL sink are unaffected
                   either way.
    """
    global _exporter
    _exporter = exporter


# source: infrastructure/config.py — CORTEX_CLAUDE_DIR isolates all local data.
# Existing filesystem ownership in this module is unchanged; no infrastructure
# import is introduced into core to resolve the same configuration root.
_root_override = os.environ.get("CORTEX_CLAUDE_DIR", "").strip()
_LOG_PATH = (
    (Path(_root_override).expanduser() if _root_override else Path.home() / ".claude")
    / "methodology"
    / "telemetry.jsonl"
)
try:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
except OSError:
    logger.warning("Cannot create telemetry directory: %s", _LOG_PATH.parent)

_lock = threading.Lock()
_counters: dict[str, dict[str, float | int]] = {}


class TelemetrySample(TypedDict):
    """One operation, finalized with the concrete MCP response when available."""

    ts: float
    op: str
    latency_ms: float
    bytes_in: int
    bytes_out: int
    result_count: int
    ok: bool
    tier: str | None
    reranked_count: int


@dataclass
class _Capture:
    samples: list[TelemetrySample] = field(default_factory=list)
    closed: bool = False


_capture: ContextVar[_Capture | None] = ContextVar("telemetry_capture", default=None)


@contextmanager
def capture_records() -> Iterator[list[TelemetrySample]]:
    """Defer publication; copied worker contexts publish directly after closure."""
    captured = _Capture()
    token = _capture.set(captured)
    try:
        yield captured.samples
    finally:
        # asyncio.to_thread copies context; a cancelled caller can finish first.
        # Lock closure against late worker appends so no sample is stranded.
        with _lock:
            captured.closed = True
        _capture.reset(token)


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
    """Capture one operation, or publish immediately outside an MCP request."""
    if _disabled():
        return
    retrieval = retrieval_metrics()
    sample: TelemetrySample = {
        "ts": time.time(),
        "op": op,
        "latency_ms": latency_ms,
        "bytes_in": bytes_in,
        "bytes_out": bytes_out,
        "result_count": result_count,
        "ok": ok,
        "tier": retrieval.tier,
        "reranked_count": retrieval.reranked_count,
    }
    captured = _capture.get()
    with _lock:
        if captured is not None and not captured.closed:
            captured.samples.append(sample)
            return
    publish_record(sample)


def _update_counters(sample: TelemetrySample) -> None:
    """Keep full-precision latency in counters, as before JSONL rounding."""
    with _lock:
        c = _counters.setdefault(
            sample["op"],
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
        c["ok" if sample["ok"] else "fail"] += 1
        c["bytes_in"] += sample["bytes_in"]
        c["bytes_out"] += sample["bytes_out"]
        c["result_count"] += sample["result_count"]
        c["latency_ms_sum"] += sample["latency_ms"]
        c["latency_ms_max"] = max(c["latency_ms_max"], sample["latency_ms"])


def publish_record(sample: TelemetrySample) -> None:
    """Publish one finalized sample to counters, JSONL and the optional exporter."""
    if _disabled():
        return
    _update_counters(sample)
    # source: existing JSONL contract rounds latency_ms to three decimal places.
    record_line = {**sample, "latency_ms": round(sample["latency_ms"], 3)}
    try:
        line = json.dumps(record_line) + "\n"
        with open_rotating_log(_LOG_PATH, len(line.encode("utf-8"))) as f:
            f.write(line)
    except OSError:
        logger.warning("Cannot append telemetry sample: %s", _LOG_PATH, exc_info=True)
    exporter = _exporter
    if exporter is not None:
        try:
            exporter.export(record_line)
        except Exception:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
            logger.debug("telemetry exporter raised; sample dropped", exc_info=True)


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
    "query_methodology",
    "session_start",
    "auto_recall",
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
