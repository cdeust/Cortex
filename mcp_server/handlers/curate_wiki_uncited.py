"""curate_wiki's I6-D7 reverse loop: report uncited deliberate memories.

Split out of ``curate_wiki.py`` (was pushing that file past the 500-line
limit, CLAUDE.md "Code Quality Rules") — also a genuine separation of
concerns (Move 5): job-planning (cluster/coverage/reauthor jobs, the
"what should get written next" question) and this report (the "what
already exists but is undocumented" question) are independent read
paths that happen to share one MCP tool surface (``curate_wiki``'s
``report_uncited_deliberate`` flag) for discoverability.

Read-only by construction: this module never calls ``wiki_write``,
``insert_citation``, or any other write path. It lists candidates; a
human or the in-session LLM decides what, if anything, to author.
"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.memory_store import get_shared_store
from mcp_server.infrastructure.pg_store_wiki import list_uncited_deliberate_memories
from mcp_server.observability import silent_failure


def report_uncited_deliberate(limit: int) -> dict[str, Any]:
    """I6-D7 reverse loop: report, never write. See
    ``list_uncited_deliberate_memories`` for the precise criteria.

    Best-effort: any DB failure degrades to an empty report rather than
    raising — this is a documentation-planning aid, not a load-bearing
    write path.
    """
    try:
        store = get_shared_store()
        candidates = list_uncited_deliberate_memories(store._conn, limit=limit)
    except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
        silent_failure.note("curate_wiki_uncited.candidates", exc)
        candidates = []
    return {
        "mode": "report_uncited_deliberate",
        "candidates": candidates,
        "candidate_count": len(candidates),
        "instructions": (
            "These are active, deliberate, verifiably-important memories "
            "with no wiki.citations row — nothing documents them yet. "
            "This is a report, not an action: no page or citation was "
            "written. To document one, find or create the right page "
            "(consider `curate_wiki` without report_uncited_deliberate "
            "for the normal cluster/coverage job flow, or author "
            "directly) and call `wiki_write(..., "
            "memory_ids=[<id>, ...])` so it earns a citation."
        ),
    }
