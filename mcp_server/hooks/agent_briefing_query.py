"""The configured store and the two-pass briefing query for agent_briefing.

Both passes are store operations (ADR-1112): the hook holds no database
connection of its own.

source: ADR-0484"""

from __future__ import annotations

from typing import Any

from mcp_server.hooks.agent_briefing_log import _log
from mcp_server.hooks.agent_briefing_sqlite import _MAX_MEMORIES, _MIN_HEAT
from mcp_server.infrastructure.hook_recall_queries import (
    briefing_agent_rows,
    briefing_team_rows,
)

__all__ = ["_MAX_MEMORIES", "_MIN_HEAT", "_store", "_fetch_agent_context"]


def _store() -> Any:
    """The configured store (SQLite or PostgreSQL), shared by the process."""
    from mcp_server.infrastructure.memory_store import get_shared_store  # noqa: PLC0415 — hook latency boundary

    return get_shared_store()


def _entry(row: dict, source: str) -> dict:
    return {
        "id": row["id"],
        "content": (row.get("content") or "")[:300],
        "heat": row.get("heat", 0),
        "source": source,
    }


def _team_source(store: Any, row: dict) -> str:
    """PostgreSQL names the authoring agent; the SQLite banner never did."""
    if getattr(store, "backend", "") == "sqlite":
        return "team"
    return f"team:{row.get('agent_context', '')}"


def _fetch_agent_context(
    store: Any, agent_name: str, keywords: list[str], project_root: str | None = None
) -> list[dict]:
    """Fetch relevant memories for agent briefing.

    Two passes: (1) agent-scoped memories matching the task keywords, prior
    work by this specialist; (2) project team decisions, whatever the
    authoring agent. Each result keeps the memory ``id``: the injection
    receipt (T2) records exactly which memories entered the agent's context.
    """
    results: list[dict] = []
    if keywords:
        try:
            rows = store.call(
                briefing_agent_rows,
                agent_name,
                list(keywords),
                project_root,
                _MIN_HEAT,
                _MAX_MEMORIES,
            )
            results.extend(_entry(r, "agent-prior") for r in rows)
        except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
            _log(f"agent-scoped query failed: {exc}")
    remaining = _MAX_MEMORIES - len(results)
    if remaining > 0:
        try:
            rows = store.call(
                briefing_team_rows, agent_name, len(keywords), project_root, remaining
            )
            results.extend(_entry(r, _team_source(store, r)) for r in rows)
        except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
            _log(f"team decisions query failed: {exc}")
    return results
