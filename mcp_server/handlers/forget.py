"""Handler: forget — delete a memory by ID.

Supports hard delete (permanent) and soft delete (heat=0, is_stale=1).
Protected memories require explicit force=True to remove.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.core.gist_extraction import parse_artifact_pointer
from mcp_server.infrastructure.artifact_gc import delete_artifact_if_unreferenced
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore, get_shared_store
from mcp_server.infrastructure.pg_store_wiki import delete_claims_for_memory
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
            # Soft delete is recoverable, so the raw content must survive with
            # it. Reported explicitly rather than omitted so a caller can tell
            # "kept on purpose" from "we forgot to look" (issue #366).
            "artifact_deleted": False,
        }

    # ── Hard delete: cross-substrate, and the two orderings below are
    # load-bearing (issue #366).
    #
    # The artifact path must be read BEFORE the row goes — it lives in the
    # memory body, which is about to be unreachable.
    artifact_path = parse_artifact_pointer(mem.get("content") or "")

    # Wiki claims must go BEFORE the row: wiki.claim_events.memory_id is
    # ON DELETE SET NULL (infrastructure/pg_schema.py), so once the memory row
    # is deleted the claim survives with a NULL link and can no longer be
    # found by memory_id at all.
    claims_deleted = _delete_derived_claims(store, memory_id)

    deleted = store.delete_memory(memory_id)

    # The reference check must run AFTER the row is gone, or the memory being
    # forgotten counts itself as a live referrer and nothing is ever collected.
    artifact_deleted = (
        delete_artifact_if_unreferenced(store._conn, artifact_path)
        if deleted
        else False
    )

    return {
        "deleted": deleted,
        "method": "hard",
        "memory_id": memory_id,
        "content_preview": mem["content"][:80],
        "artifact_deleted": artifact_deleted,
        "claims_deleted": claims_deleted,
    }


def _delete_derived_claims(store: MemoryStore, memory_id: int) -> int:
    """Remove wiki claim_events derived from ``memory_id``; return the count.

    Never raises: a wiki table that is absent or unreachable (SQLite installs
    without the wiki schema, a degraded connection) must not block the deletion
    the user asked for. Returns 0 when nothing was removed, and logs the reason
    so a silent miss is still observable.
    """
    try:
        return int(delete_claims_for_memory(store._conn, memory_id))
    except Exception as exc:  # noqa: BLE001 — mechanism boundary, see docstring
        logger.warning(
            "wiki claims for memory %s could not be removed: %s", memory_id, exc
        )
        return 0


# Telemetry-instrumented public entry. Records latency / byte volume
# / result count per call (Popper C6 read/write ratio audit).
handler = instrument("forget", _handler_impl, result_count_key=None)
