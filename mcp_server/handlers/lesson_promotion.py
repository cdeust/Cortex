"""Handler: lesson_promotion — propose promotion jobs for validated lessons.

source: ADR-0419"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.core.lesson_promotion import (
    build_promotion_jobs,
    promotion_instructions,
)
from mcp_server.handlers._tool_meta import READ_ONLY
from mcp_server.infrastructure.memory_store import get_shared_store
from mcp_server.infrastructure.pg_store_lesson_promotion import (
    list_lesson_promotion_candidates,
)
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from mcp_server.infrastructure.sqlite_store_lesson_promotion import (
    list_lesson_promotion_candidates as list_candidates_sqlite,
)
from mcp_server.observability import silent_failure

logger = logging.getLogger(__name__)


def _list_candidates(store: Any, limit: int) -> list[dict[str, Any]]:
    """Backend dispatch for the candidate query.

    source: ADR-0419"""
    if isinstance(store, SqliteMemoryStore):
        return list_candidates_sqlite(store._conn, limit=limit)
    return list_lesson_promotion_candidates(store._conn, limit=limit)


schema = {
    "title": "Lesson promotion",
    "annotations": READ_ONLY,
    "description": (
        "Propose promotion jobs for lessons (memories tagged 'lesson' "
        "or 'lesson-candidate') that have demonstrated usage evidence "
        "(recalled or rated useful at least once). Each job carries the "
        "lesson's memory_id, content, and a heuristic suggested_kind "
        "('rule'|'trigger'|'wiki') the in-session LLM may follow or "
        "override. The server NEVER calls add_rule/create_trigger/"
        "wiki_write itself — a rule reshapes every future recall, so "
        "the decision stays with the reviewer. Distinct from "
        "`curate_wiki` (wiki authoring jobs from memory clusters, not "
        "lesson promotion), `add_rule`/`create_trigger`/`wiki_write` "
        "(the actual promotion actions this handler only proposes), "
        "and `assess_coverage`/`detect_gaps` (read-only audits with no "
        "actionable job queue). Read-only. Latency ~30ms. Returns "
        "{jobs: [{memory_id, content, suggested_kind, tags, "
        "useful_count, access_count}], candidate_count, instructions}."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "limit": {
                "type": "integer",
                "default": 10,
                "minimum": 1,
                "maximum": 100,
                "description": "Maximum number of promotion jobs to return.",
            },
        },
    },
}


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build lesson-promotion jobs from validated lesson/lesson-candidate memories.

    source: ADR-0419"""
    args = args or {}
    limit = int(args.get("limit") or 10)

    store: Any = None
    try:
        store = get_shared_store()
        candidates = _list_candidates(store, limit)
    except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure + the log below
        # source: ADR-0419
        silent_failure.note("lesson_promotion.candidates", exc)
        logger.warning(
            "lesson-promotion candidate query failed on %s; reporting an "
            "empty backlog. This is a degraded result, not an empty store.",
            type(store).__name__ if store is not None else "<unresolved store>",
            exc_info=True,
        )
        candidates = []

    jobs = build_promotion_jobs(candidates)

    return {
        "jobs": jobs,
        "candidate_count": len(candidates),
        "returned": len(jobs),
        "instructions": promotion_instructions(),
    }
