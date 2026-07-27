"""Handler: lesson_promotion — propose promotion jobs for validated lessons.

M-D6 (INC 7.6): the lesson (a memory tagged ``lesson`` or
``lesson-candidate``) is the canonical form; ``memory_rules``,
``prospective_memories``, and wiki pages are traced projections of it.
This handler is the read-only planner — it never calls ``add_rule``,
``create_trigger``, or ``wiki_write`` itself. Same architecture as
``curate_wiki``: the server assembles candidates and a structured prompt;
the in-session LLM reads each job, decides whether and how to promote,
and executes the promotion via the existing handlers (passing
``source_memory_id`` / ``memory_ids`` so the pointer is queryable both
ways), then closes the loop with a ``remember(supersedes_id=...,
tags=[..., 'promoted:<kind>'])`` call on the lesson itself.

No auto-promotion, ever: a rule reshapes every future recall (high
stakes — Move 7), so the decision stays with the LLM/user reading the
job, exactly like ``curate_wiki`` never authors a page on its own.
"""

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

    Same composition-root concern, and the same shape, as
    `get_grooming_health._count_promotion_candidates`: the eligibility
    query exists in two SQL dialects because `@>` and
    `jsonb_array_elements_text` have no SQLite translation, and the
    psycopg-compat wrapper translates lexical conventions only, never
    jsonb operators. Dispatching on the store type is what keeps this
    handler working on the plugin's default backend (issue #220).
    """
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

    Best-effort: any DB failure degrades to an empty job list rather than
    raising — this is a planning aid, not a load-bearing write path (same
    contract as ``curate_wiki_uncited.report_uncited_deliberate``).
    """
    args = args or {}
    limit = int(args.get("limit") or 10)

    store: Any = None
    try:
        store = get_shared_store()
        candidates = _list_candidates(store, limit)
    except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure + the log below
        # Was a bare swallow. The SQLite backend (the plugin DEFAULT) raised
        # `unrecognized token: "@"` here on every call because the PG dialect
        # ran unconditionally, and this handler reported an empty backlog
        # instead of an error — the failure was invisible for as long as
        # nobody compared it against the store (issue #220). The fallback
        # stays (callers rely on the empty-list contract) but it is no longer
        # silent: §13.1 F1 — every failure mode emits an actionable signal.
        # Two signals, deliberately: `silent_failure` is the repo-wide
        # machine-readable channel (#197 family 2), while the log names the
        # BACKEND, which is the one fact that distinguishes this dialect bug
        # from a genuinely empty store.
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
