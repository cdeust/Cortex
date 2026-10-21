"""auto_recall and agent_briefing queries, as store operations.

Moved verbatim from ``hooks/auto_recall.py``, ``hooks/agent_briefing_query.py``,
``hooks/agent_briefing_role.py`` and ``hooks/agent_briefing_sqlite.py``
(ADR-1112 increment 2). Each operation serves both backends: the SQLite
store lends its compatibility connection, the PostgreSQL store a pool
connection, and the dialect follows the connection. Values and FTS phrases
are bound, never interpolated as SQL.

source: ADR-1112 (as operations); ADR-0485, ADR-0484, ADR-1085 (the queries)
"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.sqlite_scope_clause import directory_scope_clause
from mcp_server.infrastructure.store_operations import store_operation
from mcp_server.shared.project_scope import project_ancestors

# source: ADR-0485
_AUTO_RECALL_SQL = """
SELECT m.id, m.content,
       effective_heat(m, NOW()) AS heat,
       m.domain, m.agent_context, m.is_protected,
       m.created_at, m.source_attribution, m.is_stale,
       ts_rank_cd(m.content_tsv, q) AS rank
FROM memories m
     JOIN current_memories cm ON cm.id = m.id,
     plainto_tsquery('english', %s) q
WHERE m.content_tsv @@ q
  AND effective_heat(m, NOW()) >= %s
  AND NOT m.is_benchmark
  AND m.superseded_by_id IS NULL
  AND (m.is_global = TRUE OR m.directory_context = ANY(%s::TEXT[]))
-- source: ADR-1106 -- exact ties go to the newer memory.
ORDER BY m.is_protected DESC, rank DESC, effective_heat(m, NOW()) DESC,
         m.created_at DESC, m.id DESC
LIMIT %s
"""
# source: ADR-0484
_PG_AGENT_SQL = """
SELECT m.id, m.content, effective_heat(m, NOW()) AS heat, m.agent_context
FROM memories m JOIN current_memories cm ON cm.id = m.id
WHERE m.agent_context = %s
  AND effective_heat(m, NOW()) >= %s
  AND (m.is_global = TRUE OR m.directory_context = ANY(%s::TEXT[]))
  AND NOT m.is_benchmark
  AND m.superseded_by_id IS NULL
  AND m.content_tsv @@ plainto_tsquery('english', %s)
-- source: ADR-1106 -- exact ties go to the newer memory.
ORDER BY effective_heat(m, NOW()) DESC, m.created_at DESC, m.id DESC
LIMIT %s
"""
# source: ADR-0484
_PG_TEAM_SQL = """
SELECT m.id, m.content, effective_heat(m, NOW()) AS heat, m.agent_context
FROM memories m JOIN current_memories cm ON cm.id = m.id
WHERE m.is_team_decision = TRUE
  AND (m.agent_context IS NULL OR m.agent_context != %s OR %s = 0)
  AND (m.is_global = TRUE OR m.directory_context = ANY(%s::TEXT[]))
  AND NOT m.is_benchmark
  AND m.superseded_by_id IS NULL
-- source: ADR-1106 -- exact ties go to the newer memory.
ORDER BY effective_heat(m, NOW()) DESC, m.created_at DESC, m.id DESC
LIMIT %s
"""
# source: ADR-1085 (role-scoped briefing)
_PG_ROLE_SQL = (
    "SELECT m.id, m.content, effective_heat(m, NOW()) AS heat FROM memories m "
    "JOIN current_memories cm ON cm.id = m.id "
    "WHERE m.agent_context = %s AND effective_heat(m, NOW()) >= %s "
    "AND NOT COALESCE(m.is_team_decision, FALSE) AND NOT m.is_benchmark "
    "AND m.superseded_by_id IS NULL "
    "AND (m.is_global = TRUE OR m.directory_context = ANY(%s::TEXT[])) "
    # source: ADR-1106 -- exact ties go to the newer memory.
    "ORDER BY effective_heat(m, NOW()) DESC, m.created_at DESC, m.id DESC "
    "LIMIT %s"
)


def _is_sqlite(conn: Any) -> bool:
    from mcp_server.infrastructure.sqlite_compat import PsycopgCompatConnection  # noqa: PLC0415 — the SQLite adapter is optional at import time

    return isinstance(conn, PsycopgCompatConnection)


def _dicts(rows: list[Any]) -> list[dict]:
    return [dict(r) for r in rows]


@store_operation
def auto_recall_rows(
    conn: Any, query: str, min_heat: float, project_root: str | None, limit: int
) -> list[dict]:
    """FTS recall for UserPromptSubmit (PostgreSQL), project-scoped."""
    params = (query[:200], min_heat, project_ancestors(project_root), limit)
    return _dicts(conn.execute(_AUTO_RECALL_SQL, params).fetchall())


def _sqlite_base(project_root: str | None) -> tuple[str, list]:
    scope, params = directory_scope_clause(project_ancestors(project_root), "m.")
    base = (
        "SELECT m.id, m.content, m.heat_base AS heat, m.agent_context "
        "FROM current_memories m WHERE NOT COALESCE(m.is_benchmark, 0) "
        "AND m.superseded_by_id IS NULL " + scope
    )
    return base, list(params)


@store_operation
def briefing_agent_rows(
    conn: Any,
    agent: str,
    keywords: list[str],
    project_root: str | None,
    min_heat: float,
    limit: int,
) -> list[dict]:
    """Prior work by this specialist matching the task keywords."""
    if _is_sqlite(conn):
        base, params = _sqlite_base(project_root)
        # Five task keywords; FTS5 quoted phrases escape operators (ADR-0484).
        phrase = " AND ".join('"' + k.replace('"', '""') + '"' for k in keywords[:5])
        sql = (
            base + " AND m.agent_context = ? AND m.heat_base >= ? "  # noqa: S608 — fixed SQL and placeholder-only scope; bound values
            "AND m.id IN (SELECT rowid FROM memories_fts WHERE memories_fts MATCH ?) "
            # source: ADR-1106 -- exact ties go to the newer memory.
            "ORDER BY m.heat_base DESC, m.id DESC LIMIT ?"
        )
        return _dicts(
            conn.execute(sql, (*params, agent, min_heat, phrase, limit)).fetchall()
        )
    ancestors = project_ancestors(project_root)
    params_pg = (agent, min_heat, ancestors, " ".join(keywords[:5]), limit)
    return _dicts(conn.execute(_PG_AGENT_SQL, params_pg).fetchall())


@store_operation
def briefing_team_rows(
    conn: Any, agent: str, keyword_count: int, project_root: str | None, limit: int
) -> list[dict]:
    """Team decisions in scope, shared across agents."""
    if _is_sqlite(conn):
        base, params = _sqlite_base(project_root)
        sql = (
            base + " AND m.is_team_decision = 1 "
            "AND (m.agent_context IS NULL OR m.agent_context != ? OR ? = 0) "
            # source: ADR-1106 -- exact ties go to the newer memory.
            "ORDER BY m.heat_base DESC, m.id DESC LIMIT ?"
        )
        return _dicts(
            conn.execute(sql, (*params, agent, keyword_count, limit)).fetchall()
        )
    params_pg = (agent, keyword_count, project_ancestors(project_root), limit)
    return _dicts(conn.execute(_PG_TEAM_SQL, params_pg).fetchall())


@store_operation
def briefing_role_rows(
    conn: Any, agent: str, project_root: str | None, min_heat: float, limit: int
) -> list[dict]:
    """The specialist's own prior memories when the host gave no task."""
    if _is_sqlite(conn):
        scope, params = directory_scope_clause(project_ancestors(project_root), "m.")
        sql = (
            "SELECT m.id, m.content, m.heat_base AS heat FROM current_memories m "  # noqa: S608 — only placeholder-bearing scope fragment; all values bound
            "WHERE m.agent_context = ? AND m.heat_base >= ? "
            "AND NOT COALESCE(m.is_team_decision, 0) "
            "AND NOT COALESCE(m.is_benchmark, 0) AND m.superseded_by_id IS NULL "
            + scope
            # source: ADR-1106 -- exact ties go to the newer memory.
            + "ORDER BY m.heat_base DESC, m.id DESC LIMIT ?"
        )
        return _dicts(conn.execute(sql, (agent, min_heat, *params, limit)).fetchall())
    params_pg = (agent, min_heat, project_ancestors(project_root), limit)
    return _dicts(conn.execute(_PG_ROLE_SQL, params_pg).fetchall())
