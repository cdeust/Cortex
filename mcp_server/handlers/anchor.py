"""Handler: anchor — mark a memory as compaction-resistant.

Anchored memories survive context compaction and heat decay:
  - heat set to 1.0 (maximum)
  - is_protected = True (blocks forget + compression)
  - importance set to 1.0
  - _anchor tag added

Use this for critical facts, active decisions, and architectural invariants
that must persist across session boundaries.
"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

# ── Schema ────────────────────────────────────────────────────────────────────

schema = {
    "description": (
        "Mark a memory as compaction-resistant by setting heat=1.0, "
        "is_protected=true, importance=1.0, and adding an `_anchor` tag — "
        "so the memory survives context compaction, heat decay, and "
        "consolidation pruning, and cannot be deleted without force=true. "
        "The optional reason is stored as an `[ANCHOR: ...]` content prefix "
        "for audit. Use this for critical facts, active architectural "
        "decisions, and operating principles that must persist across "
        "session boundaries. Distinct from `rate_memory` (raises confidence "
        "via metamemory, doesn't pin), `remember` (creates memories, "
        "doesn't pin), and `checkpoint` (whole-state snapshot, not per-"
        "memory). Mutates the memories table. Latency ~20ms. Returns "
        "{anchored, memory_id, content_preview} or {error}."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["memory_id"],
        "properties": {
            "memory_id": {
                "type": "integer",
                "description": "Integer ID of the memory to anchor (returned by recall or remember).",
                "minimum": 1,
                "examples": [42, 1024],
            },
            "reason": {
                "type": "string",
                "description": (
                    "Short justification for why this memory is being anchored. "
                    "Stored as a contextual prefix on the content (max 40 chars used in tag)."
                ),
                "examples": [
                    "Load-bearing architectural decision",
                    "Active production incident root cause",
                ],
            },
            "is_global": {
                "type": "boolean",
                "description": "If true, mark the memory as visible to all projects/domains, not just its origin.",
                "default": False,
            },
        },
    },
}

# ── Singleton ─────────────────────────────────────────────────────────────────

_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        settings = get_memory_settings()
        _store = MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)
    return _store


# ── Handler ───────────────────────────────────────────────────────────────────


def _build_anchor_tags(mem: dict[str, Any], reason: str) -> list[str]:
    """Build updated tag list with anchor tags added."""
    import json as _json

    existing_tags = mem.get("tags", [])
    if isinstance(existing_tags, str):
        try:
            existing_tags = _json.loads(existing_tags)
        except (ValueError, TypeError):
            existing_tags = []

    tags = list(existing_tags)
    if "_anchor" not in tags:
        tags.append("_anchor")
    if reason:
        anchor_tag = f"_anchor:{reason[:40]}"
        if anchor_tag not in tags:
            tags.append(anchor_tag)
    return tags


def _build_anchor_content(content: str, reason: str) -> str:
    """Apply anchor prefix to content if reason is given."""
    if reason and not content.startswith("[ANCHOR:"):
        return f"[ANCHOR: {reason}] {content}"
    return content


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Anchor a memory — make it compaction-resistant."""
    import json as _json

    args = args or {}
    memory_id = args.get("memory_id")
    reason = (args.get("reason") or "").strip()

    if memory_id is None:
        return {"anchored": False, "reason": "memory_id is required"}

    memory_id = int(memory_id)
    store = _get_store()

    mem = store.get_memory(memory_id)
    if mem is None:
        return {"anchored": False, "reason": f"memory not found: {memory_id}"}

    tags = _build_anchor_tags(mem, reason)
    content = _build_anchor_content(mem.get("content", ""), reason)
    is_global = args.get("is_global", False)

    store._conn.execute(
        "UPDATE memories SET heat = 1.0, is_protected = TRUE, importance = 1.0, "
        "tags = %s::jsonb, content = %s, is_global = %s WHERE id = %s",
        (_json.dumps(tags), content, is_global, memory_id),
    )
    store._conn.commit()

    return {
        "anchored": True,
        "memory_id": memory_id,
        "reason": reason or "no reason given",
        "is_global": is_global,
        "tags": tags,
        "content_preview": content[:120],
    }
