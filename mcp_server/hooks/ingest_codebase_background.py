"""Background worker that invokes ``ingest_codebase`` for a project.

Spawned by the SessionStart hook when the cached graph is stale or
missing. Runs detached from the parent process so SessionStart returns
immediately.

Invocation:
    python -m mcp_server.hooks.ingest_codebase_background /path/to/project

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


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "Usage: python -m mcp_server.hooks.ingest_codebase_background <project_root>",
            file=sys.stderr,
        )
        sys.exit(2)

    project_root = sys.argv[1]

    # Lazy import so Claude Code hooks can fire even if core deps are
    # still installing on first session.
    try:
        from mcp_server.handlers.ingest_codebase import handler
    except Exception as exc:
        print(f"[bg-ingest] ingest_codebase import failed: {exc}", file=sys.stderr)
        sys.exit(1)

    args: dict[str, Any] = {
        "project_path": project_root,
        # Don't force reindex — handler picks up cached graph when fresh
        # and auto-reindexes when stale. Identical to interactive use.
    }

    try:
        result = asyncio.run(handler(args))
    except Exception as exc:
        print(f"[bg-ingest] handler crashed: {exc}", file=sys.stderr)
        sys.exit(1)

    if isinstance(result, dict) and result.get("error"):
        print(f"[bg-ingest] handler returned error: {result['error']}", file=sys.stderr)
        sys.exit(1)

    counts = {k: v for k, v in (result or {}).items() if isinstance(v, (int, float))}
    print(f"[bg-ingest] ingest_codebase ok: {counts}")
    sys.exit(0)


if __name__ == "__main__":
    main()
