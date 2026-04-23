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
from mcp_server.handlers._tool_meta import IDEMPOTENT_WRITE
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

logger = logging.getLogger(__name__)

schema = {
    "title": "Checkpoint (save / restore working state)",
    "annotations": IDEMPOTENT_WRITE,
    "outputSchema": {
        "type": "object",
        "required": ["action"],
        "properties": {
            "action": {"type": "string", "enum": ["save", "restore"]},
            "checkpoint_id": {
                "type": "string",
                "description": "UUID of the saved or restored checkpoint row.",
            },
            "restored_context": {
                "type": "string",
                "description": "Human-readable reconstruction of prior session state. Present on restore.",
            },
            "memories_attached": {
                "type": "integer",
                "description": "Count of hot + anchored + directory-relevant memories fused into the restore payload.",
            },
            "epoch": {
                "type": "integer",
                "description": "Session epoch counter the checkpoint ties to.",
            },
        },
    },
    "description": (
        "Hippocampal-replay-style save/restore of whole working state across "
        "context compaction events (McClelland 1995). `save` writes a "
        "checkpoint row capturing current task, files-being-edited, key "
        "decisions, open questions, planned next steps, and active errors, "
        "tied to the current epoch. `restore` reconstructs post-compaction "
        "context by fusing the latest checkpoint with anchored + hot + "
        "directory-relevant memories. Use `save` before risking compaction; "
        "use `restore` immediately after. Distinct from `anchor` (per-"
        "memory pinning, no task state), `remember` (creates one memory, "
        "no whole-state snapshot), and `query_methodology` (cognitive "
        "profile, not session state). Mutates the checkpoints table on "
        "save; read-only on restore. Latency ~50ms (save) / ~100ms "
        "(restore). Returns {action, checkpoint_id, restored_context?, "
        "memories_attached}."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["action"],
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "'save' to write a new checkpoint capturing current state; "
                    "'restore' to reconstruct context from the active checkpoint "
                    "plus relevant memories."
                ),
                "enum": ["save", "restore"],
                "examples": ["save", "restore"],
            },
            "directory": {
                "type": "string",
                "description": "Current working directory the work is happening in.",
                "examples": ["/Users/alice/code/cortex"],
            },
            "current_task": {
                "type": "string",
                "description": "Brief description of the active task or goal.",
                "examples": [
                    "Fixing recall regression introduced by FlashRank cache change"
                ],
            },
            "files_being_edited": {
                "type": "array",
                "description": "Absolute or repo-relative paths of files currently open for editing.",
                "items": {"type": "string"},
                "default": [],
                "examples": [
                    ["mcp_server/core/pg_recall.py", "tests_py/core/test_pg_recall.py"]
                ],
            },
            "key_decisions": {
                "type": "array",
                "description": "Important decisions made during this session that the next session must respect.",
                "items": {"type": "string"},
                "default": [],
                "examples": [
                    ["Use HNSW m=16 not IVFFlat", "Defer rerank cache fix to ADR-0043"]
                ],
            },
            "open_questions": {
                "type": "array",
                "description": "Unresolved questions that block progress.",
                "items": {"type": "string"},
                "default": [],
                "examples": [["Why does R@10 drop on multi-hop queries?"]],
            },
            "next_steps": {
                "type": "array",
                "description": "Planned next actions, in order.",
                "items": {"type": "string"},
                "default": [],
                "examples": [
                    ["Run benchmark on clean DB", "Compare WRRF weights vs paper"]
                ],
            },
            "active_errors": {
                "type": "array",
                "description": "Errors currently being debugged.",
                "items": {"type": "string"},
                "default": [],
                "examples": [["psycopg.OperationalError: connection refused"]],
            },
            "custom_context": {
                "type": "string",
                "description": "Free-form additional context worth preserving across compaction.",
            },
            "session_id": {
                "type": "string",
                "description": "Session identifier this checkpoint belongs to. Defaults to 'default'.",
                "default": "default",
                "examples": ["dbaca0ec-b346-464a-84b9-afe97b91d27d"],
            },
        },
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
