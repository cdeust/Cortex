"""Embedding-upgrade cycle: re-embed fallback memories once the model arrives.

The scheduled other half of the #169 zero-download fallback. When a session ran
on the download-free algorithmic provider (``embedding_model = 'fallback'``) and
a later session finds the neural model present, this maintenance cycle re-embeds
those memories with the neural encoder and restamps them 'neural' — so the
store transparently upgrades to full-fidelity vectors over time instead of
leaving two incompatible spaces side by side forever.

Bounded per run (``_MAX_UPGRADE_PER_CYCLE``) so a large backlog is drained
across several consolidations rather than in one blocking pass, mirroring the
other streaming cycles. No-op when the current encoder is still fallback (no
neural model to upgrade to) or when the store has no fallback worklist.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.infrastructure.embedding_engine import EmbeddingEngine
from mcp_server.infrastructure.memory_store import MemoryStore

logger = logging.getLogger(__name__)

# source: matches sleep_compute.run_sleep_compute_streamed's max_reembed=100
# bound (mcp_server/core/sleep_compute.py) — the same per-cycle re-embed budget
# already used for stale/compressed embeddings, reused here for parity.
_MAX_UPGRADE_PER_CYCLE = 100


def run_embedding_upgrade_cycle(
    store: MemoryStore, embeddings: EmbeddingEngine
) -> dict[str, Any]:
    """Re-embed up to ``_MAX_UPGRADE_PER_CYCLE`` fallback memories with neural.

    postcondition: returns ``{"upgraded": n}`` (and a ``reason`` when it skips).
    Only runs when the encoder currently resolves to the neural model; each
    upgraded memory is re-embedded and restamped 'neural' via
    ``store.reembed_memory``. Non-fatal: failures report zero upgrades.
    """
    if not hasattr(store, "select_fallback_embeddings") or not hasattr(
        store, "reembed_memory"
    ):
        return {"upgraded": 0, "reason": "store has no fallback worklist"}
    if getattr(embeddings, "mode", "neural") != "neural":
        return {"upgraded": 0, "reason": "no neural model available yet"}
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
