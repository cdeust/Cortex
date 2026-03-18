"""Handler: checkpoint — hippocampal replay checkpoint/restore.

Creates working state checkpoints before context compaction and
reconstructs context after compaction via hippocampal replay.

Two operations:
  - save: Store current working state as a checkpoint
  - restore: Reconstruct context from checkpoint + hot memories
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.core.replay import format_restoration
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

logger = logging.getLogger(__name__)

schema = {
    "description": "Hippocampal replay: save/restore working state across context compaction events.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["save", "restore"],
                "description": "save: create checkpoint. restore: reconstruct context.",
            },
            "directory": {"type": "string", "description": "Current working directory"},
            "current_task": {"type": "string", "description": "What you're working on"},
            "files_being_edited": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Files currently being modified",
            },
            "key_decisions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Important decisions made this session",
            },
            "open_questions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Unresolved questions",
            },
            "next_steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Planned next actions",
            },
            "active_errors": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Errors currently being debugged",
            },
            "custom_context": {
                "type": "string",
                "description": "Any additional context to preserve",
            },
            "session_id": {"type": "string", "description": "Session identifier"},
        },
        "required": ["action"],
    },
}

_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        settings = get_memory_settings()
        _store = MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)
    return _store


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    if not args or not args.get("action"):
        return {"error": "action is required (save or restore)"}

    action = args["action"]

    if action == "save":
        return _save_checkpoint(args)
    elif action == "restore":
        return _restore_context(args)
    else:
        return {"error": f"Unknown action: {action}"}


def _save_checkpoint(args: dict) -> dict:
    """Create a working state checkpoint."""
    store = _get_store()
    get_memory_settings()

    checkpoint_id = store.insert_checkpoint(
        {
            "session_id": args.get("session_id", "default"),
            "directory_context": args.get("directory", ""),
            "current_task": args.get("current_task", ""),
            "files_being_edited": args.get("files_being_edited", []),
            "key_decisions": args.get("key_decisions", []),
            "open_questions": args.get("open_questions", []),
            "next_steps": args.get("next_steps", []),
            "active_errors": args.get("active_errors", []),
            "custom_context": args.get("custom_context", ""),
            "epoch": store.get_current_epoch(),
        }
    )

    return {
        "status": "saved",
        "checkpoint_id": checkpoint_id,
        "epoch": store.get_current_epoch(),
    }


def _partition_hot_memories(
    all_hot: list[dict],
    max_memories: int,
) -> tuple[list[dict], set[int], list[dict], set[int]]:
    """Split hot memories into anchored and recent partitions."""
    anchored = [m for m in all_hot if m.get("is_protected")][:max_memories]
    anchor_ids = {m["id"] for m in anchored}
    recent = [
        m for m in all_hot if m["id"] not in anchor_ids and not m.get("is_protected")
    ][:max_memories]
    recent_ids = {m["id"] for m in recent}
    return anchored, anchor_ids, recent, recent_ids


def _restore_context(args: dict) -> dict:
    """Reconstruct context from checkpoint + memories."""
    store = _get_store()
    settings = get_memory_settings()
    directory = args.get("directory", "")
    max_memories = settings.REPLAY_MAX_RESTORE_MEMORIES

    checkpoint = store.get_active_checkpoint()
    all_hot = store.get_hot_memories(min_heat=0.0, limit=200)
    anchored, anchor_ids, recent, recent_ids = _partition_hot_memories(
        all_hot, max_memories
    )

    if directory:
        hot_mems = store.get_memories_for_directory(directory, min_heat=0.3)
    else:
        hot_mems = store.get_hot_memories(min_heat=0.5, limit=max_memories * 2)
    hot = [m for m in hot_mems if m["id"] not in anchor_ids | recent_ids][:max_memories]

    formatted = format_restoration(
        checkpoint=checkpoint,
        anchored_memories=anchored,
        recent_memories=recent,
        hot_memories=hot,
        directory=directory,
    )

    return {
        "status": "restored",
        "checkpoint": checkpoint is not None,
        "anchored_count": len(anchored),
        "recent_count": len(recent),
        "hot_count": len(hot),
        "epoch": checkpoint.get("epoch", 0) if checkpoint else 0,
        "formatted": formatted,
    }
