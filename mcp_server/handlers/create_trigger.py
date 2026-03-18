"""Handler: create_trigger — create a prospective memory trigger.

Prospective memory is future-oriented: "remind me when X happens".
Triggers are stored in the prospective_memories table and checked at
session start (query_methodology) and on demand.

Trigger types:
  - keyword:  fires when the user's message contains the keyword
  - time:     fires after a specified ISO datetime
  - file:     fires when a specific file is accessed/modified
  - domain:   fires when a specific domain becomes active
"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

# ── Schema ────────────────────────────────────────────────────────────────────

schema = {
    "description": "Create a prospective memory trigger: a future-oriented reminder that fires when a condition is met (keyword, time, file, or domain).",
    "inputSchema": {
        "type": "object",
        "required": ["content", "trigger_condition"],
        "properties": {
            "content": {
                "type": "string",
                "description": "The reminder content to surface when the trigger fires",
            },
            "trigger_condition": {
                "type": "string",
                "description": "The condition value (keyword string, ISO datetime, file path, or domain name)",
            },
            "trigger_type": {
                "type": "string",
                "enum": ["keyword", "time", "file", "domain"],
                "description": "Trigger type (default: keyword)",
            },
            "target_directory": {
                "type": "string",
                "description": "Restrict trigger to a specific project directory (optional)",
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


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a prospective memory trigger."""
    args = args or {}

    content = (args.get("content") or "").strip()
    trigger_condition = (args.get("trigger_condition") or "").strip()

    if not content:
        return {"created": False, "reason": "content is required"}
    if not trigger_condition:
        return {"created": False, "reason": "trigger_condition is required"}

    trigger_type = args.get("trigger_type", "keyword")
    if trigger_type not in ("keyword", "time", "file", "domain"):
        return {"created": False, "reason": f"invalid trigger_type: {trigger_type}"}

    target_directory = (args.get("target_directory") or "").strip() or None

    store = _get_store()

    pm_id = store.insert_prospective_memory(
        {
            "content": content,
            "trigger_condition": trigger_condition,
            "trigger_type": trigger_type,
            "target_directory": target_directory,
            "is_active": True,
            "triggered_count": 0,
        }
    )

    return {
        "created": True,
        "trigger_id": pm_id,
        "trigger_type": trigger_type,
        "trigger_condition": trigger_condition,
        "content": content,
        "target_directory": target_directory,
        "active_triggers": store.count_active_triggers(),
    }
