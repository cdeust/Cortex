"""Phase 5: latency-class registry for MCP tool handlers.

Source: docs/program/phase-5-pool-admission-design.md §1.1, ADR-0045 R6.

Each tool declares which connection pool it may acquire:

    interactive — hot-path (recall, remember, anchor, ...).
                  Bounded to interactive_pool (max=8, timeout=5s).
                  Admission semaphore default: Semaphore(4) per tool.

    batch       — long-running writers (consolidate, wiki_pipeline,
                  seed_project, ingest_*).
                  Bounded to batch_pool (max=2, timeout=30min).
                  Admission semaphore default: Semaphore(1) per tool.

Rationale (Erlang): without latency classes a single connection singleton
serializes all work. With them, interactive and batch streams are
isolated and their queueing behavior is predictable (bounded-buffer
M/M/c/K instead of M/D/1 with c=1).

The registry is a module-level dict so:
  * Adding a new tool requires one entry here — no scattered tags
    across 65 handler files.
  * Tests can enumerate all tools and assert a class is declared.
  * The admission middleware (step 5) reads from this registry.
"""

from __future__ import annotations

from typing import Literal

LatencyClass = Literal["interactive", "batch"]

# Canonical tool → class map. Any tool not listed here falls through to
# the `default_class` function below which classifies by name heuristics.
_LATENCY_CLASS: dict[str, LatencyClass] = {
    # ── Interactive (hot path) ────────────────────────────────────────
    "recall": "interactive",
    "recall_hierarchical": "interactive",
    "remember": "interactive",
    "anchor": "interactive",
    "forget": "interactive",
    "checkpoint": "interactive",
    "detect_domain": "interactive",
    "list_domains": "interactive",
    "explore_features": "interactive",
    "query_methodology": "interactive",
    "memory_stats": "interactive",
    "get_causal_chain": "interactive",
    "get_methodology_graph": "interactive",
    "get_project_story": "interactive",
    "get_rules": "interactive",
    "navigate_memory": "interactive",
    "drill_down": "interactive",
    "detect_gaps": "interactive",
    "rate_memory": "interactive",
    "validate_memory": "interactive",
    "narrative": "interactive",
    "open_visualization": "interactive",
    "assess_coverage": "interactive",
    "add_rule": "interactive",
    "create_trigger": "interactive",
    "sync_instructions": "interactive",
    # Wiki read/navigate stays interactive (single-page granularity)
    "wiki_read": "interactive",
    "wiki_list": "interactive",
    "wiki_link": "interactive",
    "wiki_write": "interactive",
    "wiki_adr": "interactive",
    # ── Batch (long-running) ──────────────────────────────────────────
    "consolidate": "batch",
    "seed_project": "batch",
    "codebase_analyze": "batch",
    "backfill_memories": "batch",
    "import_sessions": "batch",
    "rebuild_profiles": "batch",
    "record_session_end": "batch",
    "ingest_codebase": "batch",
    "ingest_prd": "batch",
    "wiki_reindex": "batch",
    "wiki_purge": "batch",
}

# Default semaphore capacity per class. Per-tool overrides live in the
# admission middleware (step 5).
DEFAULT_SEMAPHORE = {
    "interactive": 4,
    "batch": 1,
}


def classify(tool_name: str) -> LatencyClass:
    """Return the latency class for a tool.

    Falls back to heuristic: names containing "ingest", "consolidate",
    "rebuild", "seed", "backfill", "reindex", "purge", "pipeline" are
    classified as ``batch``; everything else is ``interactive``.

    Using a heuristic default keeps the registry small — adding a new
    ``recall_*`` tool won't require an entry here until its concurrency
    profile diverges from the default.
    """
    if tool_name in _LATENCY_CLASS:
        return _LATENCY_CLASS[tool_name]
    n = tool_name.lower()
    batch_markers = (
        "ingest",
        "consolidate",
        "rebuild",
        "seed",
        "backfill",
        "reindex",
        "purge",
        "pipeline",
    )
    if any(m in n for m in batch_markers):
        return "batch"
    return "interactive"


def all_registered_tools() -> list[str]:
    """Return every tool name in the registry. For tests and audits."""
    return sorted(_LATENCY_CLASS.keys())
