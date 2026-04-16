"""Handler: rate_memory — provide usefulness feedback for a memory.

Increments useful_count when a memory was helpful, then recomputes
metamemory confidence (useful_count / access_count). High-confidence
memories resist decay and rank higher in future recalls.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core import thermodynamics
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

# ── Schema ────────────────────────────────────────────────────────────────

schema = {
    "description": (
        "Record a usefulness verdict for a memory that just surfaced in "
        "recall: increments useful_count when helpful and recomputes "
        "metamemory confidence as useful_count / access_count "
        "(Nelson & Narens 1990 framework). High-confidence memories resist "
        "heat decay and rank higher in future recalls; persistently "
        "unhelpful memories drift toward archival. Use this whenever a "
        "recalled memory either solved the problem or wasted attention — "
        "the feedback loop is what keeps recall accurate. Distinct from "
        "`forget` (deletes), `anchor` (pins, doesn't score), and "
        "`validate_memory` (filesystem-ref staleness, not user verdict). "
        "Mutates the memories table (access_count, useful_count, "
        "confidence). Latency ~20ms. Returns {rated, memory_id, useful, "
        "access_count, useful_count, confidence, content_preview}."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["memory_id", "useful"],
        "properties": {
            "memory_id": {
                "type": "integer",
                "description": "Integer ID of the memory to rate (returned by recall).",
                "minimum": 1,
                "examples": [42, 1024],
            },
            "useful": {
                "type": "boolean",
                "description": (
                    "true if the memory was helpful for the current task; "
                    "false if it was noise or misleading."
                ),
                "examples": [True, False],
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
    """Rate a memory and update its metamemory confidence."""
    if not args or args.get("memory_id") is None:
        return {"rated": False, "reason": "no_memory_id"}
    if args.get("useful") is None:
        return {"rated": False, "reason": "missing useful flag"}

    memory_id = int(args["memory_id"])
    useful = bool(args["useful"])

    store = _get_store()
    mem = store.get_memory(memory_id)
    if mem is None:
        return {"rated": False, "reason": "not_found", "memory_id": memory_id}

    access_count = mem.get("access_count", 0) + 1
    useful_count = mem.get("useful_count", 0) + (1 if useful else 0)

    # Recompute metamemory confidence
    confidence = thermodynamics.compute_metamemory_confidence(
        access_count, useful_count
    )
    if confidence is None:
        confidence = mem.get("confidence", 1.0)  # Not enough data yet

    store.update_memory_metamemory(memory_id, access_count, useful_count, confidence)

    return {
        "rated": True,
        "memory_id": memory_id,
        "useful": useful,
        "access_count": access_count,
        "useful_count": useful_count,
        "confidence": round(confidence, 4),
        "content_preview": mem["content"][:80],
    }
