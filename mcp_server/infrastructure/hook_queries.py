"""The hooks' read queries, as store operations (ADR-1112 increment 2).

Until this increment SessionStart, UserPromptSubmit (auto_recall) and
SubagentStart (agent_briefing) each opened a raw PostgreSQL connection of
their own. The SQL moved here verbatim; hooks now ask the store, so in
broker mode a hook opens no database connection at all. Constants that
parameterise the queries (limits, heat floors) stay in the hooks and arrive
as arguments.

SessionStart's queries run with ``SET LOCAL jit = off`` inside their own
one-statement transaction: the curation sample plans above
``jit_above_cost`` and JIT compilation dominated the hook's time
(docs/verification/codex-session-start-query-20261002.md); the hook used to
request it for its whole connection.

source: ADR-1112 (as operations); ADR-0498, ADR-0485, ADR-0484 (the queries)
"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.store_operations import store_operation

# source: ADR-0498
_ANCHORS_SQL = (
    "SELECT m.id, m.content, m.tags, m.domain, m.is_global, "
    "m.directory_context, "
    "m.created_at, m.source_attribution, m.is_stale "
    "FROM memories m JOIN current_memories cm ON cm.id = m.id "
    "WHERE m.is_protected = TRUE "
    # contract: zetetic-team-subagents memory/contract.md §8b
    "AND NOT (m.tags @> '[\"auto-captured\"]'::jsonb) "
    "AND m.superseded_by_id IS NULL "
    "AND (m.is_global = TRUE OR m.directory_context = ANY(%s::TEXT[])) "
    # source: ADR-1106 -- exact ties go to the newer memory.
    "ORDER BY effective_heat(m, NOW()) DESC, m.created_at DESC, m.id DESC LIMIT %s"
)
# source: ADR-0498
_TEAM_DECISIONS_SQL = (
    "SELECT m.id, m.content, m.domain, m.agent_context, "
    "m.created_at, m.source_attribution, m.is_stale, "
    "effective_heat(m, NOW()) AS heat "
    "FROM memories m JOIN current_memories cm ON cm.id = m.id "
    "WHERE m.is_team_decision = TRUE AND NOT m.is_benchmark "
    "AND (m.is_global = TRUE OR m.directory_context = ANY(%s::TEXT[])) "
    "AND m.agent_context != '' "
    "AND m.superseded_by_id IS NULL "
    # source: ADR-1106 -- exact ties go to the newer memory.
    "ORDER BY effective_heat(m, NOW()) DESC, m.created_at DESC, m.id DESC LIMIT 5"
)
# contract: zetetic-team-subagents memory/contract.md §8b
_HOT_SQL = (
    "SELECT id, content, domain, heat_base AS heat, tags, is_global, "
    "directory_context, "
    "created_at, source_attribution, is_stale "
    "FROM current_memories "
    "WHERE heat_base >= %s "
    "AND NOT (tags @> '[\"auto-captured\"]'::jsonb "
    "         OR tags @> '[\"memory-replica\"]'::jsonb) "
    "AND superseded_by_id IS NULL "
    "AND (is_global = TRUE OR directory_context = ANY(%s::TEXT[])) "
    # source: ADR-1106 -- exact ties go to the newer memory.
    "ORDER BY heat_base DESC, id DESC LIMIT %s"
)
# source: ADR-0498 (the sample), ADR-1107 (the narrow cut)
_CURATION_SAMPLE_SQL = (
    "SELECT m.id, m.content, m.tags, "
    "effective_heat(m, NOW()) AS effective_heat, "
    "m.created_at, m.domain "
    "FROM (SELECT id FROM memories "
    "WHERE NOT is_stale AND superseded_by_id IS NULL "
    "ORDER BY last_accessed DESC NULLS LAST, created_at DESC, id DESC "
    "LIMIT 500) newest "
    "JOIN memories m ON m.id = newest.id "
    "ORDER BY m.last_accessed DESC NULLS LAST, m.created_at DESC, m.id DESC"
)
# source: docs/verification/codex-session-start-query-20261002.md
_GROOMING_AGES_SQL = (
    "WITH lessons AS MATERIALIZED ("
    "  SELECT created_at, tags FROM memories "
    "  WHERE tags @> '[\"lesson\"]'::jsonb) "
    "SELECT "
    "  (SELECT MAX(tended) FROM wiki.pages) AS wiki_last, "
    "  (SELECT MAX(created_at) FROM lessons m "
    "     WHERE EXISTS (SELECT 1 FROM jsonb_array_elements_text(m.tags) tg "
    "                   WHERE tg LIKE 'distill-of:%')) AS distill_last, "
    "  (SELECT MAX(created_at) FROM lessons m "
    "     WHERE EXISTS (SELECT 1 FROM jsonb_array_elements_text(m.tags) tg "
    "                   WHERE tg LIKE 'promoted:%')) AS promo_last"
)
# source: ADR-0498
_CHECKPOINT_SQL = (
    "SELECT current_task, next_steps, open_questions, active_errors, "
    "key_decisions, directory_context "
    "FROM checkpoints WHERE is_active = TRUE "
    "ORDER BY created_at DESC LIMIT 1"
)


def _jit_off_rows(conn: Any, sql: str, params: tuple = ()) -> list[dict]:
    """One statement with JIT off for its own transaction only."""
    with conn.transaction():
        conn.execute("SET LOCAL jit = off")
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


@store_operation
def session_anchor_rows(conn: Any, ancestors: list[str], limit: int) -> list[dict]:
    """Protected memories in scope (project ancestors or global)."""
    return _jit_off_rows(conn, _ANCHORS_SQL, (ancestors, int(limit)))


@store_operation
def session_team_decision_rows(conn: Any, ancestors: list[str]) -> list[dict]:
    """Team decisions in scope, hottest first, at most five."""
    return _jit_off_rows(conn, _TEAM_DECISIONS_SQL, (ancestors,))


@store_operation
def session_hot_rows(
    conn: Any, min_heat: float, ancestors: list[str], limit: int
) -> list[dict]:
    """Hot memories in scope, tier-1 noise excluded."""
    return _jit_off_rows(conn, _HOT_SQL, (float(min_heat), ancestors, int(limit)))


@store_operation
def session_curation_sample(conn: Any) -> list[dict]:
    """The 500 most recently accessed live memories (curation sample)."""
    return _jit_off_rows(conn, _CURATION_SAMPLE_SQL)


@store_operation
def session_grooming_ages(conn: Any) -> dict | None:
    """Last wiki tending, distillation and promotion timestamps."""
    rows = _jit_off_rows(conn, _GROOMING_AGES_SQL)
    return rows[0] if rows else None


@store_operation
def session_active_checkpoint(conn: Any) -> dict | None:
    """The newest active checkpoint row, or None."""
    rows = _jit_off_rows(conn, _CHECKPOINT_SQL)
    return rows[0] if rows else None


@store_operation
def session_memory_count(conn: Any) -> int:
    """How many memories the store holds."""
    rows = _jit_off_rows(conn, "SELECT COUNT(*) as c FROM memories")
    return int(rows[0]["c"]) if rows else 0
