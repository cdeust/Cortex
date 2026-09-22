"""SQLite briefing adapter using the shared store. source: ADR-1085

Reuse ADR-0484's two passes and limits; heat_base matches SQLite hot-memory
queries. Values and FTS phrases are bound, never interpolated as SQL.
"""

from __future__ import annotations

from mcp_server.infrastructure.sqlite_scope_clause import directory_scope_clause
from mcp_server.shared.project_scope import project_ancestors


# source: ADR-0484
_MAX_MEMORIES = 3
# source: ADR-0484
_MIN_HEAT = 0.2


class SqliteBriefingConnection:
    """Borrow the shared store; closing the hook must not close its owner."""

    def __init__(self, store):
        self.store = store

    def close(self):
        """The process-scoped store owns the connection lifecycle."""


def fetch_sqlite_context(connection, agent, keywords, project_root):
    """Apply project and current-row visibility before both query limits."""
    scope, params = directory_scope_clause(project_ancestors(project_root), "m.")
    base = (
        "SELECT m.id, m.content, m.heat_base AS heat, m.agent_context "
        "FROM current_memories m WHERE NOT COALESCE(m.is_benchmark, 0) "
        "AND m.superseded_by_id IS NULL " + scope
    )
    conn = connection.store._conn
    results = []
    if keywords:
        # Five task keywords; FTS5 quoted phrases escape operators.
        # source: ADR-0484
        query = " AND ".join('"' + k.replace('"', '""') + '"' for k in keywords[:5])
        rows = conn.execute(
            base + " AND m.agent_context = ? AND m.heat_base >= ? "  # noqa: S608 — fixed SQL and placeholder-only scope; bound values
            "AND m.id IN (SELECT rowid FROM memories_fts WHERE memories_fts MATCH ?) "
            "ORDER BY m.heat_base DESC LIMIT ?",
            (*params, agent, _MIN_HEAT, query, _MAX_MEMORIES),
        ).fetchall()
        results.extend(_rows(rows, "agent-prior"))
    remaining = _MAX_MEMORIES - len(results)
    if remaining:
        rows = conn.execute(
            base + " AND m.is_team_decision = 1 "
            "AND (m.agent_context IS NULL OR m.agent_context != ? OR ? = 0) "
            "ORDER BY m.heat_base DESC LIMIT ?",
            (*params, agent, len(keywords), remaining),
        ).fetchall()
        results.extend(_rows(rows, "team"))
    return results


def _rows(rows, source):
    """Preserve receipt identity and the existing briefing content budget."""
    return [
        {
            "id": r["id"],
            "content": r["content"][:300],
            "heat": r["heat"],
            "source": source,
        }
        for r in rows
    ]
