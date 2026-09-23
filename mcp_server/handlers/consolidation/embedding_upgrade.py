"""Embedding-upgrade cycle: re-embed fallback memories once the model arrives.

source: ADR-0358"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from mcp_server.infrastructure.embedding_engine import EmbeddingEngine
from mcp_server.infrastructure.memory_store import MemoryStore

logger = logging.getLogger(__name__)

# source: ADR-0358
_MAX_UPGRADE_PER_CYCLE = 100


@runtime_checkable
class _FallbackWorklistStore(Protocol):
    """Capability contract for the fallback re-embed worklist.

    The SQLite store implements it; PgMemoryStore intentionally does not
    (PG installs always have the neural encoder), so absence is the
    designed degraded mode -- named, not silent. ``has_vec`` is checked
    separately (source: ADR-1089): a store can satisfy this Protocol's
    methods while its vec extension is unavailable, and re-embedding
    without a place to persist the vector is pointless work, not a
    degraded mode of this cycle.
    """

    @property
    def has_vec(self) -> bool: ...

    def select_fallback_embeddings(self, limit: int = ...) -> list[dict]: ...

    def reembed_memory(self, memory_id: int, embedding: bytes | None) -> None: ...


def run_embedding_upgrade_cycle(
    store: MemoryStore, embeddings: EmbeddingEngine
) -> dict[str, Any]:
    """Re-embed up to ``_MAX_UPGRADE_PER_CYCLE`` fallback memories with neural.

    postcondition: ``{"upgraded": n}``, or ``{"upgraded": 0, "reason":
    ...}`` and nothing touched when the encoder isn't neural or the store
    can't persist a vector (``has_vec``). Non-fatal: failures count zero.

    source: ADR-1089
    """
    if not isinstance(store, _FallbackWorklistStore):
        return {"upgraded": 0, "reason": "store has no fallback worklist"}
    if getattr(embeddings, "mode", "neural") != "neural":
        return {"upgraded": 0, "reason": "no neural model available yet"}
    if not store.has_vec:
        return {"upgraded": 0, "reason": "store cannot persist vectors (has_vec=False)"}
    try:
        candidates = store.select_fallback_embeddings(limit=_MAX_UPGRADE_PER_CYCLE)
    except Exception:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.debug("Embedding-upgrade cycle: worklist query failed (non-fatal)")
        return {"upgraded": 0}

    upgraded = 0
    for item in candidates:
        content = item.get("content")
        if not content:
            continue
        try:
            emb = embeddings.encode(content)
            if emb:
                store.reembed_memory(item["memory_id"], emb)
                upgraded += 1
        except Exception:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
            logger.debug(
                "Embedding-upgrade failed for memory %s (non-fatal)",
                item.get("memory_id"),
            )
    return {"upgraded": upgraded}
