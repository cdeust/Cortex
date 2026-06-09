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
from mcp_server.handlers.consolidation.wiki_maintenance import run_wiki_maintenance
from mcp_server.infrastructure.embedding_engine import (
    EmbeddingEngine,
    get_embedding_engine,
)
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore, get_shared_store
from mcp_server.handlers._tool_meta import IDEMPOTENT_WRITE

logger = logging.getLogger(__name__)

schema = {
    "title": "Consolidate memories",
    "annotations": IDEMPOTENT_WRITE,
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
            "wiki": {
                "type": "boolean",
                "description": (
                    "Run autonomous wiki maintenance: purge stub pages, "
                    "report classifier-reject count, and update the "
                    "curation backlog. Default true — the wiki must stay "
                    "up-to-date without a human in the loop. Set false "
                    "only when debugging consolidate."
                ),
                "default": True,
            },
            "wiki_apply_stubs": {
                "type": "boolean",
                "description": (
                    "Delete stub pages (body is majority placeholder "
                    "markers) during the autonomous wiki cycle. Default "
                    "true — stubs are unambiguous noise."
                ),
                "default": True,
            },
            "wiki_apply_classifier_rejects": {
                "type": "boolean",
                "description": (
                    "Delete pages that fail the current classifier (audit "
                    "tags, hard negatives) during the autonomous wiki "
                    "cycle. Default true — the system decides; "
                    "non-technical users cannot be expected to classify "
                    "pages by hand. Per-cycle deletion is capped by "
                    "`wiki_max_purges_per_axis` so a buggy classifier "
                    "change cannot wipe the wiki in one shot."
                ),
                "default": True,
            },
            "wiki_max_purges_per_axis": {
                "type": "integer",
                "minimum": 0,
                "description": (
                    "Cap on how many pages each purge axis (stubs, "
                    "classifier rejects) may delete in a single "
                    "consolidate cycle. Acts as a safety rail: a buggy "
                    "classifier change costs at most one cap's worth "
                    "of pages before the next cycle exposes the "
                    "regression. Default 500. Pass 0 to disable the "
                    "cap (one-shot full sweep)."
                ),
                "default": 500,
            },
        },
    },
}

_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        settings = get_memory_settings()
        _store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
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


async def _atimed(fn, *args, **kwargs) -> dict[str, Any]:
    """Async counterpart of :func:`_timed` for awaitable cycle functions."""
    t0 = time.monotonic()
    try:
        result = await fn(*args, **kwargs) or {}
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

    # Constant-memory consolidate (sharded-popping-harbor): every stage now
    # STREAMS the memory corpus in bounded chunks via
    # ``store.iter_memories_for_decay()`` (decay/compression/memify/sleep/
    # homeostatic) or a streaming reducer (emergence, wiki cluster count), so
    # peak RAM is one chunk plus bounded accumulators rather than the whole
    # ~1GB corpus. This trades the single issue-13 shared load for one bounded
    # cursor scan per stage — the correct trade at scale, where the shared list
    # would OOM. A future single-pass combined reducer can fold these scans.
    stats = _run_cycles(args, store, settings, embeddings)
    stats = _run_always_cycles(args, store, stats)

    # 2026-05-18: autonomous wiki maintenance. The wiki has to stay up
    # to date without a human in the loop, so every consolidation cycle
    # purges stale + stub pages and reports the curation backlog
    # (coverage gaps + cluster jobs). Existing pages get the same
    # treatment as freshly authored ones — nothing the system produced
    # gets a free pass once policy tightens. Failure here is non-fatal:
    # a wiki edge case must never block memory consolidation.
    if args.get("wiki", True):
        cap_raw = args.get("wiki_max_purges_per_axis", 500)
        cap = int(cap_raw) if cap_raw is not None and int(cap_raw) > 0 else None
        wiki_stats = await _atimed(
            run_wiki_maintenance,
            store,
            apply_stubs=bool(args.get("wiki_apply_stubs", True)),
            apply_classifier_rejects=bool(
                args.get("wiki_apply_classifier_rejects", True)
            ),
            max_purges_per_axis=cap,
        )
        stats["wiki"] = wiki_stats
        # Back-compat: keep ``pending_curations`` populated for callers
        # that read the legacy key (SessionStart preamble pre-2026-05-18).
        if isinstance(wiki_stats, dict) and "pending_total" in wiki_stats:
            stats["pending_curations"] = wiki_stats["pending_total"]
        else:
            stats["pending_curations"] = None

    elapsed_ms = int((time.monotonic() - start) * 1000)
    stats["duration_ms"] = elapsed_ms

    # Aggregate rollup — surfacing partial failures (issue #13, code-reviewer).
    # Without this, a caller that only reads duration_ms cannot tell that
    # one or more stages errored inside _timed.
    failed = [k for k, v in stats.items() if isinstance(v, dict) and "error" in v]
    stats["failed_stages"] = failed
    stats["status"] = "ok" if not failed else "partial"

    _log_consolidation(store, stats, elapsed_ms)

    # Update the autonomy stamp so SessionStart's TTL gate sees this run.
    # User directive 2026-05-18: consolidate must never require manual
    # invocation; the stamp closes the loop with the SessionStart hook.
    try:
        from mcp_server.hooks.consolidate_background import _write_stamp

        _write_stamp()
    except Exception as exc:
        logger.debug("consolidate stamp write failed (non-fatal): %s", exc)

    return stats


def _run_cycles(
    args: dict,
    store: MemoryStore,
    settings: Any,
    embeddings: EmbeddingEngine,
) -> dict[str, Any]:
    """Run optional maintenance cycles based on args flags.

    Each memory-consuming stage is passed no list, so it streams the corpus in
    bounded chunks (constant memory) instead of sharing a single resident load.
    """
    stats: dict[str, Any] = {}

    if args.get("decay", True):
        stats["decay"] = _timed(run_decay_cycle, store, settings, None)
        stats["plasticity"] = _timed(run_plasticity_cycle, store)
        stats["pruning"] = _timed(run_pruning_cycle, store)

    if args.get("compress", True):
        stats["compression"] = _timed(
            run_compression_cycle, store, settings, embeddings, None
        )

    if args.get("cls", True):
        stats["cls"] = _timed(run_cls_cycle, store, settings, embeddings)

    if args.get("memify", True):
        stats["memify"] = _timed(run_memify_cycle, store, None)

    if args.get("deep", False):
        stats["deep_sleep"] = _timed(run_deep_sleep, store, embeddings, None)

    return stats


def _run_always_cycles(
    args: dict,
    store: MemoryStore,
    stats: dict[str, Any],
) -> dict[str, Any]:
    """Run cycles that always execute regardless of flags."""
    stats["cascade"] = _timed(run_cascade_advancement, store)
    stats["homeostatic"] = _timed(run_homeostatic_cycle, store, None)

    if args.get("deep", False):
        stats["transfer"] = _timed(run_two_stage_transfer, store)

    def _run_emergence() -> dict[str, Any]:
        # Streaming reducer: one bounded cursor pass, no resident corpus.
        chunks = (
            store.iter_memories_for_decay()
            if hasattr(store, "iter_memories_for_decay")
            else [store.get_all_memories_for_decay()]
        )
        return emergence_metrics.generate_emergence_report_streamed(chunks) or {}

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
