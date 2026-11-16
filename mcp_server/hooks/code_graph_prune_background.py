"""Background worker that prunes orphaned code graphs from the managed cache.

Invocation:
    python -m mcp_server.hooks.code_graph_prune_background

Before issue #711 slice 2, orphaned graphs were pruned only after an
``ingest_codebase`` run had built a graph. A session that ingested nothing (a
fresh graph, no pipeline installed, an analyze failure) left every deleted
worktree's graph (0.6 to 1.1 GB each, measured 2026-10-10, issue #711) on
disk. The SessionStart hook now starts this worker when the managed cache
holds an orphan, so the removal runs detached and never inside the hook's
time budget.

When ``CORTEX_CODE_GRAPH_CACHE_MAX_GB`` sets a cap, the worker then evicts the
least recently used graphs not in use until the cache fits (slice 3b,
``code_graph_eviction``).

Exit code: 0 when every orphan and every planned eviction was removed, 1 when
at least one removal failed. The worker prints the names it removed, kept
unattributed and failed to remove on stdout, which the parent redirects to its
log file.

source: issue #711
"""

from __future__ import annotations

import sys
from pathlib import Path

from mcp_server.hooks.output_streams import use_utf8_output
from mcp_server.infrastructure import code_graph_cache, code_graph_eviction
from mcp_server.infrastructure.session_registry_roots import live_project_roots


def main() -> int:
    """Prune the managed cache once, evict over the cap, print what changed."""
    cache_dir = code_graph_cache.managed_cache_dir()
    report = code_graph_cache.prune_orphan_graphs(cache_dir)
    print(f"[bg-graph-prune] removed: {list(report.removed)}")
    print(f"[bg-graph-prune] unattributed (kept): {list(report.unattributed)}")
    print(f"[bg-graph-prune] failed: {list(report.failed)}")
    evicted_cleanly = _evict(cache_dir)  # runs even when a prune failed
    return 1 if report.failed or not evicted_cleanly else 0


def _evict(cache_dir: Path) -> bool:
    """Evict over the cap when one is set; False when a removal failed."""
    cap = code_graph_eviction.cache_cap_bytes()
    if cap is None:
        return True
    evicted = code_graph_eviction.evict_to_cap(cache_dir, cap, live_project_roots())
    print(f"[bg-graph-evict] cap: {cap} bytes, total after: {evicted.total_bytes}")
    print(f"[bg-graph-evict] removed: {list(evicted.removed)}")
    print(f"[bg-graph-evict] failed: {list(evicted.failed)}")
    if evicted.over_cap:
        print("[bg-graph-evict] still over the cap: the rest is in use or unmarked")
    return not evicted.failed


if __name__ == "__main__":
    use_utf8_output()
    from mcp_server.hooks.wiring import wire_composition_root  # noqa: PLC0415 — source: issue #560

    wire_composition_root()
    sys.exit(main())
