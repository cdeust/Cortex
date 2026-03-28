"""Deep sleep cycle: dream replay, cluster summarization, re-embedding, narration.

Simulates offline consolidation by enriching hot memories, fixing stale embeddings,
and generating auto-narration as semantic memory.
"""

from __future__ import annotations

import logging

from mcp_server.core.sleep_compute import run_sleep_compute
from mcp_server.infrastructure.embedding_engine import EmbeddingEngine
from mcp_server.infrastructure.memory_store import MemoryStore

logger = logging.getLogger(__name__)


def run_deep_sleep(store: MemoryStore, embeddings: EmbeddingEngine) -> dict:
    """Run deep sleep compute: dream replay, summarization, re-embedding."""
    memories = store.get_all_memories_for_decay()
    plan = run_sleep_compute(memories, clusters=[], directory="")

    replayed = _apply_dream_replay(store, embeddings, plan["replay_updates"])
    reembedded = _fix_stale_embeddings(
        store,
        embeddings,
        plan["stale_embeddings"],
    )
    narration_stored = _store_narration(store, embeddings, plan.get("narration", {}))

    narrative_text = plan.get("narration", {}).get("narrative_text", "")
    return {
        "replayed": replayed,
        "reembedded": reembedded,
        "cluster_summaries": len(plan["cluster_summaries"]),
        "narration_stored": narration_stored,
        "narration_preview": narrative_text[:100] if narrative_text else "",
    }


def _apply_dream_replay(
    store: MemoryStore,
    embeddings: EmbeddingEngine,
    replay_updates: list[dict],
) -> int:
    """Update enriched content for replayed memories."""
    count = 0
    for upd in replay_updates:
        try:
            new_content = upd["enriched_content"]
            new_emb = embeddings.encode(new_content)
            store.update_memory_compression(
                upd["memory_id"],
                new_content,
                new_emb,
                compression_level=0,
            )
            count += 1
        except Exception:
            logger.exception(
                "Dream replay failed for memory %s",
                upd.get("memory_id"),
            )
    return count


def _fix_stale_embeddings(
    store: MemoryStore,
    embeddings: EmbeddingEngine,
    stale_items: list[dict],
) -> int:
    """Re-embed memories with stale or missing embeddings."""
    count = 0
    for item in stale_items:
        try:
            content = item["content"]
            if not content:
                continue
            new_emb = embeddings.encode(content)
            if new_emb:
                store._conn.execute(
                    "UPDATE memories SET embedding = %s WHERE id = %s",
                    (new_emb, item["memory_id"]),
                )
                count += 1
        except Exception:
            logger.exception(
                "Re-embedding failed for memory %s",
                item.get("memory_id"),
            )
    if count:
        store._conn.commit()
    return count


def _store_narration(
    store: MemoryStore,
    embeddings: EmbeddingEngine,
    narration: dict,
) -> bool:
    """Store auto-narration as a semantic memory if meaningful."""
    narrative_text = narration.get("narrative_text", "")
    if not narrative_text or narration.get("memory_count", 0) < 5:
        return False

    try:
        emb = embeddings.encode(narrative_text)
        store.insert_memory(
            {
                "content": narrative_text,
                "embedding": emb,
                "tags": ["auto-narration", "sleep-compute"],
                "domain": "",
                "directory": "",
                "source": "sleep-compute",
                "importance": 0.6,
                "surprise": 0.0,
                "emotional_valence": 0.0,
                "confidence": 0.7,
                "heat": 0.5,
                "store_type": "semantic",
            }
        )
        return True
    except Exception:
        logger.debug("Auto-narration storage failed (non-fatal)")
        return False
