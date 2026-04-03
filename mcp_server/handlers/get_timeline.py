"""Handler: get_timeline — Temporal session browsing.

Returns memories grouped by session for timeline visualization.
Wires infrastructure (PgMemoryStore) to core (session_grouper).
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.session_grouper import group_into_sessions
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

# ── Schema ────────────────────────────────────────────────────────────────

schema = {
    "description": "Browse memories grouped by temporal sessions. Returns a timeline of sessions with memory counts, date ranges, and summaries.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": "Filter by domain (optional)",
            },
            "days": {
                "type": "integer",
                "description": "Look back N days (default 30)",
            },
            "limit": {
                "type": "integer",
                "description": "Max sessions to return (default 50)",
            },
        },
    },
}

# ── Singleton ─────────────────────────────────────────────────────────────

_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        settings = get_memory_settings()
        _store = MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)
    return _store


# ── Handler ───────────────────────────────────────────────────────────────


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return sessions with their memories for timeline browsing."""
    args = args or {}
    domain = args.get("domain", "")
    limit = min(int(args.get("limit", 50)), 200)

    store = _get_store()

    # Fetch sessions from the store (infrastructure)
    raw_sessions = store.get_sessions(domain=domain, limit=limit)

    if not raw_sessions:
        return {"sessions": [], "total": 0}

    # Enrich with core logic
    sessions = group_into_sessions(
        _flatten_session_memories(store, raw_sessions),
    )

    # Cap to limit
    sessions = sessions[:limit]

    return {
        "sessions": sessions,
        "total": len(sessions),
    }


def _flatten_session_memories(
    store: MemoryStore,
    sessions: list[dict],
) -> list[dict]:
    """Fetch actual memories for the sessions to pass to core grouper."""
    all_memories: list[dict] = []
    for sess in sessions:
        sid = sess.get("session_id", "")
        if sid:
            mems = store.get_memories_by_session(sid, limit=100)
            all_memories.extend(mems)
    return all_memories
