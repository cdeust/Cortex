"""Handler: consolidate — run decay, compression, and CLS maintenance cycles.

Thin orchestrator that delegates each cycle to a focused sub-module in
mcp_server.handlers.consolidation/.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from mcp_server.core import emergence_metrics
from mcp_server.handlers.consolidation.cascade import run_cascade_advancement
from mcp_server.handlers.consolidation.cls import run_cls_cycle
from mcp_server.handlers.consolidation.compression import run_compression_cycle
from mcp_server.handlers.consolidation.decay import run_decay_cycle
from mcp_server.handlers.consolidation.homeostatic import run_homeostatic_cycle
from mcp_server.handlers.consolidation.memify import run_memify_cycle
from mcp_server.handlers.consolidation.plasticity import run_plasticity_cycle
from mcp_server.handlers.consolidation.pruning import run_pruning_cycle
from mcp_server.handlers.consolidation.sleep import run_deep_sleep
from mcp_server.handlers.consolidation.transfer import run_two_stage_transfer
from mcp_server.infrastructure.embedding_engine import (
    EmbeddingEngine,
    get_embedding_engine,
)
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

logger = logging.getLogger(__name__)

schema = {
    "description": (
        "Run scheduled memory-system maintenance cycles: thermodynamic "
        "heat decay, full-text → gist → tag compression, episodic→semantic "
        "CLS transfer (McClelland 1995), synaptic plasticity LTP/LTD "
        "(Hebb 1949, Bi & Poo 1998), microglial pruning of orphan edges "
        "(Wang 2020), homeostatic scaling (Turrigiano 2008), cascade "
        "stage advancement (Kandel 2001), and optional deep-sleep replay. "
        "Each cycle is delegated to a focused sub-module under "
        "handlers/consolidation/; durations are tracked per stage with "
        "partial-failure rollup. Use this on a daily/weekly cadence (or "
        "after large ingest bursts) to keep recall fast and the heat "
        "distribution healthy. Distinct from `wiki_consolidate` (operates "
        "on wiki PAGES not memories) and `forget` (one-off deletion, no "
        "lifecycle). Mutates memories + entities + relationships tables. "
        "Latency varies (~5-60s typical, deep mode minutes). Returns "
        "per-cycle counters, duration_ms per stage, status (ok|partial), "
        "and failed_stages list. The `cls` and `memify` stages include "
        "`reason_for_zero` / `reason_for_inaction` when the cycle "
        "produces no mutations, distinguishing early-return from a "
        "genuine quiet-store pass (issue #14 P2)."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "decay": {
                "type": "boolean",
                "description": (
                    "Run thermodynamic heat decay (cools cold memories), plus "
                    "synaptic plasticity (LTP/LTD on co-activated edges) and "
                    "microglial pruning of orphan edges."
                ),
                "default": True,
            },
            "compress": {
                "type": "boolean",
                "description": (
                    "Run compression cycle: full-text → gist → tag for memories "
                    "that are cold but still informative."
                ),
                "default": True,
            },
            "cls": {
                "type": "boolean",
                "description": (
                    "Run Complementary Learning Systems consolidation: extract "
                    "semantic memories from clusters of episodic ones (McClelland 1995)."
                ),
                "default": True,
            },
            "memify": {
                "type": "boolean",
                "description": (
                    "Run the memify self-improvement cycle (extract reusable "
                    "lessons and rules from recent successes/failures)."
                ),
                "default": True,
            },
            "deep": {
                "type": "boolean",
                "description": (
                    "Run deep-sleep compute: dream replay, cluster summarization, "
                    "re-embedding with a fresh model, and auto-narration. Adds "
                    "two-stage hippocampal-cortical transfer. Slow — schedule "
                    "overnight or weekly, not per session."
                ),
                "default": False,
            },
        },
    },
}

_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        settings = get_memory_settings()
        _store = MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)
    return _store


def _timed(fn, *args, **kwargs) -> dict[str, Any]:
    """Run a cycle, inject duration_ms into its result dict.

    Addresses issue #13 (darval): per-stage telemetry so operators can
    see where time actually goes on real stores.
    """
    t0 = time.monotonic()
    try:
        result = fn(*args, **kwargs) or {}
    except Exception as exc:
        ms = int((time.monotonic() - t0) * 1000)
        return {"error": f"{type(exc).__name__}: {exc}", "duration_ms": ms}
    ms = int((time.monotonic() - t0) * 1000)
    if isinstance(result, dict):
        result["duration_ms"] = ms
    return result


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run maintenance cycles on the memory system."""
    args = args or {}
    settings = get_memory_settings()
    store = _get_store()
    embeddings = get_embedding_engine()
    start = time.monotonic()

    # Phase B (issue #13): load the full memory list once and thread it
    # through every stage that needs it, so consolidate does ONE load
    # instead of 6 (decay, compression, memify, homeostatic, sleep,
    # emergence). Cheap stages still load ad-hoc for standalone callers.
    memories = store.get_all_memories_for_decay()

    stats = _run_cycles(args, store, settings, embeddings, memories)
    stats = _run_always_cycles(args, store, stats, memories)

    elapsed_ms = int((time.monotonic() - start) * 1000)
    stats["duration_ms"] = elapsed_ms

    # Aggregate rollup — surfacing partial failures (issue #13, code-reviewer).
    # Without this, a caller that only reads duration_ms cannot tell that
    # one or more stages errored inside _timed.
    failed = [k for k, v in stats.items() if isinstance(v, dict) and "error" in v]
    stats["failed_stages"] = failed
    stats["status"] = "ok" if not failed else "partial"

    _log_consolidation(store, stats, elapsed_ms)
    return stats


def _run_cycles(
    args: dict,
    store: MemoryStore,
    settings: Any,
    embeddings: EmbeddingEngine,
    memories: list[dict],
) -> dict[str, Any]:
    """Run optional maintenance cycles based on args flags.

    `memories` is the consolidation-scoped snapshot so stages share one
    load across the whole run (issue #13).
    """
    stats: dict[str, Any] = {}

    if args.get("decay", True):
        stats["decay"] = _timed(run_decay_cycle, store, settings, memories)
        stats["plasticity"] = _timed(run_plasticity_cycle, store)
        stats["pruning"] = _timed(run_pruning_cycle, store)

    if args.get("compress", True):
        stats["compression"] = _timed(
            run_compression_cycle, store, settings, embeddings, memories
        )

    if args.get("cls", True):
        stats["cls"] = _timed(run_cls_cycle, store, settings, embeddings)

    if args.get("memify", True):
        stats["memify"] = _timed(run_memify_cycle, store, memories)

    if args.get("deep", False):
        stats["deep_sleep"] = _timed(run_deep_sleep, store, embeddings, memories)

    return stats


def _run_always_cycles(
    args: dict,
    store: MemoryStore,
    stats: dict[str, Any],
    memories: list[dict],
) -> dict[str, Any]:
    """Run cycles that always execute regardless of flags."""
    stats["cascade"] = _timed(run_cascade_advancement, store)
    stats["homeostatic"] = _timed(run_homeostatic_cycle, store, memories)

    if args.get("deep", False):
        stats["transfer"] = _timed(run_two_stage_transfer, store)

    def _run_emergence() -> dict[str, Any]:
        # Uses the consolidation-scoped memory list — no extra load.
        # Source: issue #13 (darval) — was importing emergence_tracker
        # which doesn't define generate_emergence_report (lives in
        # emergence_metrics). Same shape as the homeostatic_health
        # AttributeError fixed in 69d81fb.
        return emergence_metrics.generate_emergence_report(memories) or {}

    stats["emergence"] = _timed(_run_emergence)

    return stats


def _log_consolidation(
    store: MemoryStore,
    stats: dict[str, Any],
    elapsed_ms: int,
) -> None:
    """Log consolidation event to the store."""
    store.log_consolidation(
        {
            "memories_added": stats.get("cls", {}).get("new_semantics_created", 0),
            "memories_updated": stats.get("decay", {}).get("memories_decayed", 0),
            "memories_archived": stats.get("compression", {}).get(
                "compressed_to_tag", 0
            ),
            "duration_ms": elapsed_ms,
        }
    )
