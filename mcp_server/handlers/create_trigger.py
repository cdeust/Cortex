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
    "description": (
        "Create a prospective-memory trigger that Cortex auto-fires when "
        "its condition matches future context (Einstein & McDaniel 2005). "
        "Trigger types: `keyword` (fires when user message contains "
        "string), `time` (fires after ISO datetime), `file` (fires when "
        "path is accessed/modified), `domain` (fires when that cognitive "
        "domain becomes active). Triggers are checked at session start "
        "(via `query_methodology`) and on demand. Use this to leave "
        "instructions for a future session — `next time we touch X, "
        "remember Y` — that you would otherwise forget. Distinct from "
        "`add_rule` (passive recall filter applied to ALL queries, no "
        "context-match firing), `anchor` (pins a memory but doesn't fire), "
        "and `remember` (records a fact, doesn't activate on context). "
        "Mutates the prospective_memories table. Latency ~30ms. Returns "
        "{trigger_id, trigger_type, trigger_condition, content_preview}."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["content", "trigger_condition"],
        "properties": {
            "content": {
                "type": "string",
                "description": "The reminder text Cortex will surface when the trigger fires.",
                "examples": [
                    "Before changing pg_recall.py, re-read ADR-0042 on WRRF weights.",
                    "Push the v3.10 release notes draft tonight.",
                ],
            },
            "trigger_condition": {
                "type": "string",
                "description": (
                    "The condition value, interpreted per trigger_type: keyword "
                    "string for 'keyword', ISO 8601 datetime for 'time', "
                    "absolute file path for 'file', domain id for 'domain'."
                ),
                "examples": [
                    "pg_recall",
                    "2026-04-15T18:00:00Z",
                    "/Users/alice/code/cortex/mcp_server/core/pg_recall.py",
                    "cortex",
                ],
            },
            "trigger_type": {
                "type": "string",
                "description": "Mechanism the trigger fires on.",
                "enum": ["keyword", "time", "file", "domain"],
                "default": "keyword",
                "examples": ["keyword", "time"],
            },
            "target_directory": {
                "type": "string",
                "description": "If set, the trigger only fires when the active project directory matches.",
                "examples": ["/Users/alice/code/cortex"],
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
