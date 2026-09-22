"""Backend connection and the two-pass briefing query for agent_briefing.

source: ADR-0484"""

from __future__ import annotations

import os

from mcp_server.hooks.agent_briefing_log import _log
from mcp_server.shared.project_scope import project_ancestors
from mcp_server.infrastructure.backend_marker import effective_backend
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.hooks.agent_briefing_sqlite import (
    SqliteBriefingConnection,
    _MAX_MEMORIES,
    _MIN_HEAT,
    fetch_sqlite_context,
)


def _connect():
    """Select the configured backend; None when PostgreSQL is unreachable."""
    if effective_backend(os.environ) == "sqlite":
        from mcp_server.infrastructure.memory_store import get_shared_store  # noqa: PLC0415 — hook latency boundary

        return SqliteBriefingConnection(get_shared_store())
    try:
        import psycopg  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode
        from psycopg.rows import DictRow, dict_row  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode
    except ImportError:
        return None
    try:
        return psycopg.Connection[DictRow].connect(
            os.environ.get("DATABASE_URL") or get_memory_settings().DATABASE_URL,
            row_factory=dict_row,
            autocommit=True,
        )
    except psycopg.Error:
        return None


def _fetch_agent_context(
    conn, agent_name: str, keywords: list[str], project_root: str | None = None
) -> list[dict]:
    """Fetch relevant memories for agent briefing.

    Two-pass query:
    1. Agent-scoped memories (agent_context matches) — prior work by this specialist
    2. Project team decisions, regardless of the authoring agent.

    Uses FTS plainto_tsquery for speed (no embedding model needed).
    Each result keeps the memory ``id`` — the injection receipt (T2)
    records exactly which memories entered the agent's context.
    """
    if isinstance(conn, SqliteBriefingConnection):
        return fetch_sqlite_context(conn, agent_name, keywords, project_root)
    results = []
    ancestors = project_ancestors(project_root)  # source: ADR-1083

    # Pass 1: Agent-scoped memories matching keywords
    if keywords:
        try:
            rows = conn.execute(
                (
                    # source: ADR-0484
                    """
                SELECT m.id, m.content,
                       effective_heat(m, NOW()) AS heat,
                       m.agent_context
                FROM memories m
                     JOIN current_memories cm ON cm.id = m.id
                WHERE m.agent_context = %s
                  AND effective_heat(m, NOW()) >= %s
                  AND (m.is_global = TRUE OR m.directory_context = ANY(%s::TEXT[]))
                  AND NOT m.is_benchmark
                  AND m.superseded_by_id IS NULL
                  AND m.content_tsv @@ plainto_tsquery('english', %s)
                ORDER BY effective_heat(m, NOW()) DESC
                LIMIT %s
                """
                ),
                (
                    agent_name,
                    _MIN_HEAT,
                    ancestors,
                    " ".join(keywords[:5]),
                    _MAX_MEMORIES,
                ),
            ).fetchall()
            for r in rows:
                results.append(
                    {
                        "id": r["id"],
                        "content": r.get("content", "")[:300],
                        "heat": r.get("heat", 0),
                        "source": "agent-prior",
                    }
                )
        except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
            _log(f"agent-scoped query failed: {exc}")

    # Pass 2: Decisions shared across agents within project scope
    remaining = _MAX_MEMORIES - len(results)
    if remaining > 0:
        try:
            rows = conn.execute(
                (
                    # source: ADR-0484
                    """
                SELECT m.id, m.content,
                       effective_heat(m, NOW()) AS heat,
                       m.agent_context
                FROM memories m
                     JOIN current_memories cm ON cm.id = m.id
                WHERE m.is_team_decision = TRUE
                  AND (m.agent_context IS NULL OR m.agent_context != %s OR %s = 0)
                  AND (m.is_global = TRUE OR m.directory_context = ANY(%s::TEXT[]))
                  AND NOT m.is_benchmark
                  AND m.superseded_by_id IS NULL
                ORDER BY effective_heat(m, NOW()) DESC
                LIMIT %s
                """
                ),
                (agent_name, len(keywords), ancestors, remaining),
            ).fetchall()
            for r in rows:
                results.append(
                    {
                        "id": r["id"],
                        "content": r.get("content", "")[:300],
                        "heat": r.get("heat", 0),
                        "source": f"team:{r.get('agent_context', '')}",
                    }
                )
        except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
            _log(f"team decisions query failed: {exc}")

    return results
