"""curate_wiki's I6-D7 reverse loop: report uncited deliberate memories.

Read-only by construction: this module never calls ``wiki_write``,
``insert_citation``, or any other write path. It lists candidates; a
human or the in-session LLM decides what, if anything, to author.

source: ADR-0386"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.memory_store import get_shared_store
from mcp_server.infrastructure.pg_store_wiki import list_uncited_deliberate_memories
from mcp_server.observability import silent_failure


def report_uncited_deliberate(limit: int) -> dict[str, Any]:
    """I6-D7 reverse loop: report, never write.

    source: ADR-0386"""
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
