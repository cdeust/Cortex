"""Handler: forget — delete a memory by ID.

Supports hard delete (permanent) and soft delete (heat=0, is_stale=1).
Protected memories require explicit force=True to remove.
"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

# ── Schema ────────────────────────────────────────────────────────────────

schema = {
    "description": "Delete a memory by ID. Supports soft (mark stale) or hard (permanent) deletion. Protected memories require force=True.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "integer",
                "description": "ID of the memory to delete",
            },
            "soft": {
                "type": "boolean",
                "description": "If true, soft-delete (mark stale + zero heat) instead of permanent removal. Default false.",
            },
            "force": {
                "type": "boolean",
                "description": "If true, delete even if memory is protected. Default false.",
            },
        },
        "required": ["memory_id"],
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
    """Delete or soft-delete a memory."""
    if not args or args.get("memory_id") is None:
        return {"deleted": False, "reason": "no_memory_id"}

    memory_id = int(args["memory_id"])
    soft = args.get("soft", False)
    force = args.get("force", False)

    store = _get_store()
    mem = store.get_memory(memory_id)

    if mem is None:
        return {"deleted": False, "reason": "not_found", "memory_id": memory_id}

    if mem.get("is_protected") and not force:
        return {
            "deleted": False,
            "reason": "protected — use force=True to override",
            "memory_id": memory_id,
        }

    if soft:
        store.mark_memory_stale(memory_id, stale=True)
        store.update_memory_heat(memory_id, 0.0)
        return {
            "deleted": True,
            "method": "soft",
            "memory_id": memory_id,
            "content_preview": mem["content"][:80],
        }

    # Hard delete
    deleted = store.delete_memory(memory_id)
    return {
        "deleted": deleted,
        "method": "hard",
        "memory_id": memory_id,
        "content_preview": mem["content"][:80],
    }
