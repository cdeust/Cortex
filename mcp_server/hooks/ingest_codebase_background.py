"""Background worker that invokes ``ingest_codebase`` for a project.

Spawned by two triggers, both detached so the parent returns immediately:
  * the SessionStart hook, when the cached graph is missing or older than
    the TTL (``pipeline_graph_ttl.graph_is_stale``); and
  * the PostToolUse ``post_commit_reindex`` hook, after a commit that
    touched indexable source — there it passes ``--reindex`` because the
    commit IS the change signal, so the graph must be rebuilt even though
    a cached one exists.

Invocation:
    python -m mcp_server.hooks.ingest_codebase_background /path/to/project
    python -m mcp_server.hooks.ingest_codebase_background /path/to/project --reindex

Without ``--reindex`` the handler reuses a fresh cached graph and only
re-analyses when the cache is stale/absent (identical to interactive
use). With ``--reindex`` it forces ``analyze_codebase`` to run.

Exit code:
  * 0 on success
  * 1 on recoverable error (logged, won't crash loop)
  * 2 on fatal error (no project_root)

Output goes to the redirected stdout (the parent's log file).
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)

_MIN_ARGC = 2  # source: structural — program name + <project_root>


def main() -> None:
    if len(sys.argv) < _MIN_ARGC:
        print(
            "Usage: python -m mcp_server.hooks.ingest_codebase_background "
            "<project_root>",
            file=sys.stderr,
        )
        sys.exit(2)

    project_root = sys.argv[1]
    force_reindex = "--reindex" in sys.argv[2:]

    # Lazy import so Claude Code hooks can fire even if core deps are
    # still installing on first session.
    try:
        from mcp_server.handlers.ingest_codebase import handler  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)
    except Exception as exc:  # noqa: BLE001 — failure is reported to stderr; execution degrades, never crashes
        print(f"[bg-ingest] ingest_codebase import failed: {exc}", file=sys.stderr)
        sys.exit(1)

    # Without --reindex: reuse a fresh cached graph, auto-reindex when
    # stale (SessionStart trigger). With --reindex: force analyze_codebase
    # because a commit already told us the source changed (commit trigger).
    args: dict[str, Any] = {
        "project_path": project_root,
        "force_reindex": force_reindex,
    }

    try:
        result = asyncio.run(handler(args))
    except Exception as exc:  # noqa: BLE001 — failure is reported to stderr; execution degrades, never crashes
        print(f"[bg-ingest] handler crashed: {exc}", file=sys.stderr)
        sys.exit(1)

    if isinstance(result, dict) and result.get("error"):
        print(f"[bg-ingest] handler returned error: {result['error']}", file=sys.stderr)
        sys.exit(1)

    counts = {k: v for k, v in (result or {}).items() if isinstance(v, (int, float))}
    mode = "reindex" if force_reindex else "cached-or-stale"
    print(f"[bg-ingest] ingest_codebase ok ({mode}): {counts}")
    sys.exit(0)


if __name__ == "__main__":
    # No-op inside the headless wiki-authoring subprocess (see
    # _headless_guard): prevents recursion + memory pollution when
    # ``claude -p --setting-sources user`` loads the user hooks.
    from mcp_server.hooks._headless_guard import (
        exit_if_headless_authoring_child,
    )
    from mcp_server.hooks._store_lifecycle import close_shared_store_on_exit

    exit_if_headless_authoring_child()
    # issue #398: main() calls sys.exit() on every path; wrapping the whole
    # call in this context manager guarantees the store (and its psycopg
    # pools' non-daemon threads) is closed before the process actually ends.
    with close_shared_store_on_exit():
        main()
