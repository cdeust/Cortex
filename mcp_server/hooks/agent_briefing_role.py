"""Promptless native role/project context, never inferred task context.

source: ADR-1085
"""

from mcp_server.hooks.agent_briefing_query import _fetch_agent_context
from mcp_server.hooks.agent_briefing_sqlite import (
    SqliteBriefingConnection,
    _MAX_MEMORIES,
    _MIN_HEAT,
)
from mcp_server.infrastructure.sqlite_scope_clause import directory_scope_clause
from mcp_server.shared.project_scope import project_ancestors


def fetch_role_context(conn, agent, project_root):
    """Team decisions first; existing role-prior heat order fills unused slots."""
    result = _fetch_agent_context(conn, agent, [], project_root)
    remaining = _MAX_MEMORIES - len(result)
    if not remaining:
        return result
    if isinstance(conn, SqliteBriefingConnection):
        rows = _sqlite_role_rows(conn.store._conn, agent, project_root, remaining)
    else:
        rows = _pg_role_rows(conn, agent, project_root, remaining)
    result.extend(
        {
            "id": row["id"],
            "content": row["content"][:300],
            "heat": row["heat"],
            "source": "role-prior",
        }
        for row in rows
    )
    return result


def _sqlite_role_rows(conn, agent, project_root, remaining):
    scope, params = directory_scope_clause(project_ancestors(project_root), "m.")
    return conn.execute(
        "SELECT m.id, m.content, m.heat_base AS heat FROM current_memories m "  # noqa: S608 — only placeholder-bearing scope fragment; all values bound
        "WHERE m.agent_context = ? AND m.heat_base >= ? "
        "AND NOT COALESCE(m.is_team_decision, 0) "
        "AND NOT COALESCE(m.is_benchmark, 0) AND m.superseded_by_id IS NULL "
        + scope
        + "ORDER BY m.heat_base DESC LIMIT ?",
        (agent, _MIN_HEAT, *params, remaining),
    ).fetchall()


def _pg_role_rows(conn, agent, project_root, remaining):
    return conn.execute(
        "SELECT m.id, m.content, effective_heat(m, NOW()) AS heat FROM memories m "
        "JOIN current_memories cm ON cm.id = m.id "
        "WHERE m.agent_context = %s AND effective_heat(m, NOW()) >= %s "
        "AND NOT COALESCE(m.is_team_decision, FALSE) AND NOT m.is_benchmark "
        "AND m.superseded_by_id IS NULL "
        "AND (m.is_global = TRUE OR m.directory_context = ANY(%s::TEXT[])) "
        "ORDER BY effective_heat(m, NOW()) DESC LIMIT %s",
        (agent, _MIN_HEAT, project_ancestors(project_root), remaining),
    ).fetchall()
