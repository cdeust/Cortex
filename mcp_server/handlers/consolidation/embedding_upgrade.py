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
    designed degraded mode — named, not silent. runtime_checkable
    isinstance resolves members statically (3.12+ getattr_static), which
    real stores and test fakes with real methods both satisfy.
    """

    def select_fallback_embeddings(self, limit: int = ...) -> list[dict]: ...

    def reembed_memory(self, memory_id: int, embedding: bytes | None) -> None: ...


def run_embedding_upgrade_cycle(
    store: MemoryStore, embeddings: EmbeddingEngine
) -> dict[str, Any]:
    """Re-embed up to ``_MAX_UPGRADE_PER_CYCLE`` fallback memories with neural.

    postcondition: returns ``{"upgraded": n}`` (and a ``reason`` when it skips).
    Only runs when the encoder currently resolves to the neural model; each
    upgraded memory is re-embedded and restamped 'neural' via
    ``store.reembed_memory``. Non-fatal: failures report zero upgrades.

    ``upgraded`` counts memories successfully re-encoded and restamped —
    that count stays accurate even when the store cannot persist a vector
    at all (``has_vec is False``, e.g. sqlite-vec unavailable). In that
    case the result also carries ``vectors_persisted: 0`` and a ``reason``,
    so a caller cannot read "upgraded: N" as "N vectors written" when none
    were (issue #634). Stores without a ``has_vec`` attribute (PostgreSQL,
    test doubles) are assumed vector-capable, unchanged from before.
    """
    if not isinstance(store, _FallbackWorklistStore):
        return {"upgraded": 0, "reason": "store has no fallback worklist"}
    if getattr(embeddings, "mode", "neural") != "neural":
        return {"upgraded": 0, "reason": "no neural model available yet"}
    try:
        candidates = store.select_fallback_embeddings(limit=_MAX_UPGRADE_PER_CYCLE)
    except Exception:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.debug("Embedding-upgrade cycle: worklist query failed (non-fatal)")
        return {"upgraded": 0}

    has_vec = getattr(store, "has_vec", True)
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
    result: dict[str, Any] = {"upgraded": upgraded}
    if not has_vec and upgraded:
        result["vectors_persisted"] = 0
        result["reason"] = "sqlite-vec unavailable — restamped, no vector written"
    return result
