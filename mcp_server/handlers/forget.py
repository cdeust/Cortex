"""Handler: forget — delete a memory by ID.

Supports hard delete (permanent) and soft delete (heat=0, is_stale=1).
Protected memories require explicit force=True to remove.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from mcp_server.core.gist_extraction import parse_artifact_pointer
from mcp_server.infrastructure.artifact_gc import delete_artifact_if_unreferenced
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.memory_store import MemoryStore, get_shared_store
from mcp_server.infrastructure.wiki_memory_pages import remove_derived_pages
from mcp_server.handlers._tool_meta import DESTRUCTIVE
from mcp_server.handlers._telemetry_wrap import instrument

logger = logging.getLogger(__name__)

# ── Schema ────────────────────────────────────────────────────────────────

schema = {
    "title": "Forget memory",
    "annotations": DESTRUCTIVE,
    "description": (
        "Delete a memory by integer ID via direct DELETE on the memories "
        "table (hard) or by setting is_stale=true + heat=0 (soft, "
        "recoverable via SQL). Protected/anchored memories are refused "
        "unless force=true. Use this to remove genuinely-wrong memories or "
        "accidental captures. Distinct from `rate_memory(useful=false)` "
        "(downweights without removing — prefer for low-value memories), "
        "`anchor` (protect from deletion), and `validate_memory` (mark "
        "stale based on filesystem refs, not user verdict). Mutates the "
        "memories table; hard delete is irreversible. Latency ~10ms. "
        "Returns {deleted, method, memory_id, content_preview, reason?}."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["memory_id"],
        "properties": {
            "memory_id": {
                "type": "integer",
                "description": (
                    "Integer ID of the memory to delete (returned by recall or "
                    "memory_stats)."
                ),
                "minimum": 1,
                "examples": [42, 1024],
            },
            "soft": {
                "type": "boolean",
                "description": (
                    "If true, soft-delete: set is_stale=true and heat=0 instead "
                    "of permanently dropping the row. Recoverable via SQL."
                ),
                "default": False,
            },
            "force": {
                "type": "boolean",
                "description": (
                    "If true, delete even if the memory is protected (anchored). "
                    "Use sparingly — anchored memories are usually load-bearing."
                ),
                "default": False,
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
        _store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    return _store


# ── Handler ───────────────────────────────────────────────────────────────


async def _handler_impl(args: dict[str, Any] | None = None) -> dict[str, Any]:
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
            # source: ADR-0392
            "artifact_deleted": False,
        }

    # source: ADR-0392 — compression keeps the original in original_content
    artifact_paths = {
        parse_artifact_pointer(mem.get(field) or "")
        for field in ("content", "original_content")
    } - {None}

    # source: ADR-1111 — one transaction over every copy; raises, never partial
    report = store.erase_memory(memory_id)
    pages_removed, artifact_deleted = 0, False
    if report.deleted:
        # after the commit: a failure here is residue, not "nothing erased"
        pages_removed = report.after_commit(
            "pages",
            lambda: remove_derived_pages(Path(WIKI_ROOT), memory_id, report.page_paths),
            0,
        )
        artifact_deleted = report.after_commit(
            "artifact",
            lambda: any(
                [
                    delete_artifact_if_unreferenced(store._conn, p)
                    for p in artifact_paths
                ]
            ),
            False,
        )

    return {
        "deleted": report.deleted,
        "method": "hard",
        "memory_id": memory_id,
        "content_preview": mem["content"][:80],
        "artifact_deleted": artifact_deleted,
        "claims_deleted": report.counts.get("claims", 0),
        "erased": report.counts,
        "pages_removed": pages_removed,
        "fts_method": report.fts_method,
        "wal_truncated": report.wal_truncated,
        "complete": report.complete,
        "residue": report.residue,
    }


# source: ADR-0392
handler = instrument("forget", _handler_impl, result_count_key=None)
