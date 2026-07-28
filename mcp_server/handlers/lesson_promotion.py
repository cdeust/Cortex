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
from mcp_server.observability import silent_failure

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

    try:
        store = get_shared_store()
        candidates = list_lesson_promotion_candidates(store._conn, limit=limit)
    except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
        silent_failure.note("lesson_promotion.candidates", exc)
        candidates = []

    jobs = build_promotion_jobs(candidates)

    return {
        "jobs": jobs,
        "candidate_count": len(candidates),
        "returned": len(jobs),
        "instructions": promotion_instructions(),
    }
