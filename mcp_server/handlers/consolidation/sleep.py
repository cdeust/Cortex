"""Deep sleep cycle: dream replay, cluster summarization, re-embedding, narration.

Simulates offline consolidation by enriching hot memories, fixing stale embeddings,
and generating auto-narration as semantic memory.
"""

from __future__ import annotations

import logging

from mcp_server.core.sleep_phases import run_two_phase_consolidation
from mcp_server.infrastructure.embedding_engine import EmbeddingEngine
from mcp_server.infrastructure.memory_store import MemoryStore

logger = logging.getLogger(__name__)


def run_deep_sleep(
    store: MemoryStore,
    embeddings: EmbeddingEngine,
    memories: list[dict] | None = None,
    cue: str | None = None,
) -> dict:
    """Run deep sleep compute as an NREM/REM two-phase consolidation (F1).

    The offline pass is routed through ``run_two_phase_consolidation``: an
    NREM-like exact-replay phase (delegating verbatim to the existing
    ``sleep_compute`` single pass — dream replay, summarization, re-embedding,
    narration) followed by a REM-like recombination/abstraction phase (schema
    formation + merge over any provided clusters). The NREM plan keys
    (``replay_updates`` / ``stale_embeddings`` / ``cluster_summaries`` /
    ``narration``) are unchanged, so the downstream apply steps are unaffected;
    the split adds a ``sleep_phases`` block with per-phase counts.

    F2 targeted reactivation. An optional ``cue`` (topic / tag / entity /
    free-text) biases *which* memories preferentially replay in the NREM phase.
    With no cue (the default) replay is chosen purely by heat, exactly as
    pre-F2 — identity.

    Ablation: ``CORTEX_ABLATE_SLEEP_PHASES=1`` (Mechanism.SLEEP_PHASES) skips
    the REM phase, falling back to exactly the single-pass NREM consolidation.
    ``CORTEX_ABLATE_TARGETED_REACTIVATION=1`` (Mechanism.TARGETED_REACTIVATION)
    forces the cue off so replay selection is heat-only, as pre-F2.

    When the consolidate handler pre-loads the memory list (issue #13) we
    reduce over it directly. When called standalone (``memories is None``) we
    STREAM via the chunked decay cursor so peak RAM is one chunk plus the
    bounded replay/stale/narration accumulators — not the whole corpus (the
    old ``get_all_memories_for_decay()`` materialized 500k+ rows at once).
    """
    if memories is None:
        chunks: object = store.iter_memories_for_decay()
    else:
        chunks = [memories]
    plan = run_two_phase_consolidation(chunks, clusters=[], directory="", cue=cue)

    replayed_ids = _apply_dream_replay(store, embeddings, plan["replay_updates"])
    reembedded = _fix_stale_embeddings(
        store,
        embeddings,
        plan["stale_embeddings"],
    )
    narration_stored = _store_narration(store, embeddings, plan.get("narration", {}))

    narrative_text = plan.get("narration", {}).get("narrative_text", "")
    # F1 phase telemetry: last-cycle NREM/REM counts + the phase order actually
    # run (["nrem","rem"] normally; ["nrem"] when SLEEP_PHASES is ablated). The
    # consolidate orchestrator forwards this to system_vitals for cortex-viz.
    phases = plan.get("sleep_phases", {})
    return {
        "sleep_phases": phases,
        "replayed": len(replayed_ids),
        # IDs replayed this cycle: the active-forgetting pass reads these as the
        # sleep-protection (recently_active) signal — replayed memories are
        # exempt from the ongoing forgetting signal (Davis & Zhong 2017). The
        # consolidate orchestrator pops this key before returning (plumbing,
        # not a reported metric).
        "replayed_ids": replayed_ids,
        "reembedded": reembedded,
        "cluster_summaries": len(plan["cluster_summaries"]),
        "narration_stored": narration_stored,
        "narration_preview": narrative_text[:100] if narrative_text else "",
    }


def _apply_dream_replay(
    store: MemoryStore,
    embeddings: EmbeddingEngine,
    replay_updates: list[dict],
) -> list[int]:
    """Update enriched content for replayed memories; return the IDs replayed."""
    replayed: list[int] = []
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
            replayed.append(int(upd["memory_id"]))
        except Exception:
            logger.exception(
                "Dream replay failed for memory %s",
                upd.get("memory_id"),
            )
    return replayed


def _fix_stale_embeddings(
    store: MemoryStore,
    embeddings: EmbeddingEngine,
    stale_items: list[dict],
) -> int:
    """Re-embed memories with stale or missing embeddings.

    Phase 5: batched UPDATEs run on the batch pool.
    """
    count = 0
    with store.acquire_batch() as conn:
        for item in stale_items:
            try:
                content = item["content"]
                if not content:
                    continue
                new_emb = embeddings.encode(content)
                if new_emb:
                    conn.execute(
                        "UPDATE memories SET embedding = %s WHERE id = %s",
                        (new_emb, item["memory_id"]),
                    )
                    count += 1
            except Exception:
                logger.exception(
                    "Re-embedding failed for memory %s",
                    item.get("memory_id"),
                )
    return count


# Minimum memories behind a narration for it to be worth storing.
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_MIN_NARRATION_MEMORIES = 5


def _store_narration(
    store: MemoryStore,
    embeddings: EmbeddingEngine,
    narration: dict,
) -> bool:
    """Store auto-narration as a semantic memory if meaningful."""
    narrative_text = narration.get("narrative_text", "")
    if not narrative_text or narration.get("memory_count", 0) < _MIN_NARRATION_MEMORIES:
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
                # M-D2 (7.4): dream-replay auto-narration — machine-
                # synthesized, same rationale as CLS/memify.
                "write_class": "derived",
            }
        )
        return True
    except Exception:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.debug("Auto-narration storage failed (non-fatal)")
        return False
