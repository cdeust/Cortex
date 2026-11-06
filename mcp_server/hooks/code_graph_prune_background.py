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

Exit code: 0 when every orphan was removed, 1 when at least one removal
failed. The worker prints the names it removed, kept unattributed and failed
to remove on stdout, which the parent redirects to its log file.

source: issue #711
"""

from __future__ import annotations

import sys

from mcp_server.hooks.output_streams import use_utf8_output
from mcp_server.infrastructure import code_graph_cache


def main() -> int:
    """Prune the managed cache once and print what was removed and kept."""
    report = code_graph_cache.prune_orphan_graphs(code_graph_cache.managed_cache_dir())
    print(f"[bg-graph-prune] removed: {list(report.removed)}")
    print(f"[bg-graph-prune] unattributed (kept): {list(report.unattributed)}")
    print(f"[bg-graph-prune] failed: {list(report.failed)}")
    return 1 if report.failed else 0


if __name__ == "__main__":
    use_utf8_output()
    from mcp_server.hooks.wiring import wire_composition_root  # noqa: PLC0415 — source: issue #560

    wire_composition_root()
    sys.exit(main())
