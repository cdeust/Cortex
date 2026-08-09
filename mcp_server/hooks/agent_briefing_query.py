"""PostgreSQL connection + the two-pass briefing query for agent_briefing.

Split out of ``agent_briefing.py`` (issue #401 — that file exceeded the
project's 300-line cap, CLAUDE.md § Code Style) to isolate the hook's only
I/O (PG connect + the two SELECT passes) from prompt parsing and
event-processing control flow.
"""

from __future__ import annotations

import os

from mcp_server.hooks.agent_briefing_log import _log

_DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost:5432/cortex")
_MAX_MEMORIES = 3
_MIN_HEAT = 0.2


def _connect():
    """Open the briefing's PG connection; None when PG is unreachable."""
    try:
        import psycopg  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode
        from psycopg.rows import DictRow, dict_row  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode
    except ImportError:
        return None
    try:
        return psycopg.Connection[DictRow].connect(
            _DATABASE_URL, row_factory=dict_row, autocommit=True
        )
    except psycopg.Error:
        return None


def _fetch_agent_context(conn, agent_name: str, keywords: list[str]) -> list[dict]:
    """Fetch relevant memories for agent briefing.

    Two-pass query:
    1. Agent-scoped memories (agent_context matches) — prior work by this specialist
    2. Team decisions (is_protected + is_global) — cross-agent knowledge (TMS directory)

    Uses FTS plainto_tsquery for speed (no embedding model needed).
    Each result keeps the memory ``id`` — the injection receipt (T2)
    records exactly which memories entered the agent's context.
    """
    results = []

    # Pass 1: Agent-scoped memories matching keywords
    if keywords:
        try:
            rows = conn.execute(
                """
                -- memories.heat is not a stored column; use
                -- effective_heat(m, NOW()) for lazy A3 decay (matches
                -- production recall_memories semantics).
                -- Source: pg_schema.py EFFECTIVE_HEAT_FN.
                SELECT m.id, m.content,
                       effective_heat(m, NOW()) AS heat,
                       m.agent_context
                -- JOIN current_memories: briefing content — chain heads
                -- only; join keeps m table-typed for effective_heat().
                FROM memories m
                     JOIN current_memories cm ON cm.id = m.id
                WHERE m.agent_context = %s
                  AND effective_heat(m, NOW()) >= %s
                  AND NOT m.is_benchmark
                  -- Never brief an agent with a corrected (superseded)
                  -- fact — decision 4255039 correction 8.
                  AND m.superseded_by_id IS NULL
                  AND m.content_tsv @@ plainto_tsquery('english', %s)
                ORDER BY effective_heat(m, NOW()) DESC
                LIMIT %s
                """,
                (agent_name, _MIN_HEAT, " ".join(keywords[:5]), _MAX_MEMORIES),
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

    # Pass 2: Team decisions (protected + global)
    remaining = _MAX_MEMORIES - len(results)
    if remaining > 0:
        try:
            rows = conn.execute(
                """
                SELECT m.id, m.content,
                       effective_heat(m, NOW()) AS heat,
                       m.agent_context
                -- JOIN current_memories: same pattern as pass 1.
                FROM memories m
                     JOIN current_memories cm ON cm.id = m.id
                WHERE m.is_protected = TRUE
                  AND m.is_global = TRUE
                  AND m.agent_context != %s
                  AND NOT m.is_benchmark
                  -- Superseded decisions are corrected facts — never
                  -- re-inject (decision 4255039 correction 8).
                  AND m.superseded_by_id IS NULL
                ORDER BY effective_heat(m, NOW()) DESC
                LIMIT %s
                """,
                (agent_name, remaining),
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
