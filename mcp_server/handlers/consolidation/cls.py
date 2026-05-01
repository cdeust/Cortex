"""CLS cycle: episodic -> semantic pattern extraction.

Includes causal edge discovery from entity co-occurrences via the PC algorithm.

Returns include a diagnostic ``reason_for_zero`` field when the cycle
produces no mutations (all mutational counters zero), distinguishing
early-return from a genuine "nothing to do" pass (issue #14 P2, darval).
"""

from __future__ import annotations

import logging

from mcp_server.core.causal_graph import (
    compute_co_occurrence_matrix,
    discover_causal_edges,
)
from mcp_server.core.consolidation_engine import plan_cls_consolidation
from mcp_server.core.dual_store_cls_abstraction import cluster_by_similarity
from mcp_server.infrastructure.embedding_engine import EmbeddingEngine
from mcp_server.infrastructure.memory_store import MemoryStore

logger = logging.getLogger(__name__)

# Source: issue #13 — previous cap of 500 saw ~2% of a 25k-episodic
# store and produced 0 patterns by construction. 2000 matches plasticity
# sampling and keeps PC algorithm's O(E^2) worst case tractable on a
# 10k-entity vocabulary.
_EPISODIC_SAMPLE_CAP = 2000
_SEMANTICS_SAMPLE_CAP = 2000

# CLS clustering parameters — kept at module scope so the diagnostic
# reclassification (Move 2 postcondition on `reason_for_zero`) reflects
# the exact same pairing regime used by the plan.
_MIN_PATTERN_SIZE = 3
_CLUSTER_THRESHOLD = 0.6

_EMPTY_CLS_STATS = {
    "patterns_found": 0,
    "new_semantics_created": 0,
    "skipped_inconsistent": 0,
    "skipped_duplicate": 0,
    "causal_edges_found": 0,
    "episodic_scanned": 0,
}


def run_cls_cycle(
    store: MemoryStore,
    settings,
    embeddings: EmbeddingEngine,
) -> dict:
    """Run CLS consolidation: episodic -> semantic pattern extraction.

    Verification ablation hook: when ``CORTEX_CONSOLIDATION_DISABLED=1``
    is set (E2 N-scan condition `cortex_flat`), this returns the zero
    state immediately. No episodic-to-semantic abstraction runs; the
    flat-importance store is never enriched with patterns. Source:
    tasks/verification-protocol.md E2; benchmarks/lib/n_scan_runner.py.

    Pattern extraction (`plan_cls_consolidation`) and causal-edge
    discovery (`_discover_causal_edges`) sample up to 2000 episodic
    memories each -- raised from 500 after Feynman's audit of darval's
    66K run in issue #13 showed 500 sampled 2% of the episodic store
    and produced 0 patterns by construction.

    Postcondition (issue #14 P2): the returned dict always carries the
    6 numeric counters (`patterns_found`, `new_semantics_created`,
    `skipped_inconsistent`, `skipped_duplicate`, `causal_edges_found`,
    `episodic_scanned`). When every *mutational* counter is zero (all
    except `episodic_scanned`), an additive ``reason_for_zero`` key
    classifies the early-return path: one of ``empty_episodic_scan``,
    ``below_min_pattern_size``, ``insufficient_pairs``,
    ``no_qualifying_entities``, ``passed_through``. When any mutational
    counter is non-zero, ``reason_for_zero`` is omitted.
    """
    import os as _os

    if _os.environ.get("CORTEX_CONSOLIDATION_DISABLED") == "1":
        return dict(_EMPTY_CLS_STATS)

    episodic = store.get_episodic_memories(limit=_EPISODIC_SAMPLE_CAP)
    existing_semantics = store.get_semantic_memories(limit=_SEMANTICS_SAMPLE_CAP)

    if not episodic:
        stats = _EMPTY_CLS_STATS.copy()
        stats["reason_for_zero"] = "empty_episodic_scan"
        _log_if_passed_through("cls", stats, duration_ms=0, scanned=0)
        return stats

    plan = _compute_consolidation_plan(episodic, existing_semantics, embeddings)
    created = _create_semantic_memories(store, embeddings, plan)
    causal_edges_found, qualifying_count = _discover_causal_edges(store, episodic)

    stats = {
        "patterns_found": plan["patterns_found"],
        "new_semantics_created": created,
        "skipped_inconsistent": plan["skipped_inconsistent"],
        "skipped_duplicate": plan["skipped_duplicate"],
        "causal_edges_found": causal_edges_found,
        "episodic_scanned": len(episodic),
    }

    reason = _classify_cls_zero_reason(stats, episodic, embeddings, qualifying_count)
    if reason is not None:
        stats["reason_for_zero"] = reason
        _log_if_passed_through("cls", stats, duration_ms=0, scanned=len(episodic))

    return stats


def _classify_cls_zero_reason(
    stats: dict,
    episodic: list[dict],
    embeddings: EmbeddingEngine,
    qualifying_count: int,
) -> str | None:
    """Classify the early-return path when every mutational counter is zero.

    Precondition: `stats` carries the 5 mutational counters plus
    `episodic_scanned`; `qualifying_count` is the number of entities
    that passed the PC observation threshold inside
    `_discover_causal_edges`.

    Postcondition: returns None when any mutational counter is non-zero
    (the diagnostic is additive — absent whenever the cycle produced
    output). Otherwise returns one of the enumerated reasons below.

    Priority (first match wins — most informative signal takes precedence):
      1. ``below_min_pattern_size`` — clustering produced ≥1 multi-member
         cluster but none reached ``_MIN_PATTERN_SIZE`` (patterns are
         forming, just not large enough for the min-occurrences gate).
      2. ``insufficient_pairs`` — no embedding pair crossed the cluster
         threshold AND no entity has enough mentions for the PC gate
         (the store has no pair-level signal at all).
      3. ``no_qualifying_entities`` — some entities qualify but fewer
         than ``_MIN_ENTITIES_FOR_PC``; cluster pipeline also produced
         no pairs.
      4. ``passed_through`` — every branch ran to completion and found
         nothing mutationally new (truly quiet store).
    """
    counters = (
        stats["patterns_found"],
        stats["new_semantics_created"],
        stats["skipped_inconsistent"],
        stats["skipped_duplicate"],
        stats["causal_edges_found"],
    )
    if any(c != 0 for c in counters):
        return None

    # All mutational counters zero: recompute clustering to inspect
    # pair-level signal. This path only runs when the stage produced no
    # mutations, so the O(n^2) replay is bounded by the no-op case.
    multi_member = _count_multi_member_clusters(episodic, embeddings)

    if multi_member > 0:
        # Clusters of size ≥ 2 formed but none reached _MIN_PATTERN_SIZE.
        return "below_min_pattern_size"

    # No multi-member clusters at all (no embedding pair crossed threshold).
    if qualifying_count == 0:
        return "insufficient_pairs"

    if qualifying_count < _MIN_ENTITIES_FOR_PC:
        return "no_qualifying_entities"

    return "passed_through"


def _count_multi_member_clusters(
    episodic: list[dict],
    embeddings: EmbeddingEngine,
) -> int:
    """Count clusters with ≥ 2 members by re-running greedy clustering.

    Invariant: uses the same ``_CLUSTER_THRESHOLD`` as
    ``_compute_consolidation_plan`` so the classification reflects the
    same pairing regime the cycle actually ran under.
    """

    def similarity_fn(emb_a, emb_b) -> float:
        if emb_a is None or emb_b is None:
            return 0.0
        return embeddings.similarity(emb_a, emb_b)

    try:
        clusters = cluster_by_similarity(
            episodic, similarity_fn, threshold=_CLUSTER_THRESHOLD
        )
    except Exception:
        return 0
    return sum(1 for c in clusters if len(c) >= 2)


def _log_if_passed_through(
    stage_name: str,
    stats: dict,
    duration_ms: int,
    scanned: int,
) -> None:
    """Emit an INFO log when the stage finished as a genuine no-op.

    Issue #14 P2 (darval): operators need to grep
    ``stage=<name> reason=passed_through`` to distinguish "quiet store"
    runs from early-return runs. Only fires when the classified reason
    is ``passed_through`` on either field (``reason_for_zero`` or
    ``reason_for_inaction``).
    """
    reason = stats.get("reason_for_zero") or stats.get("reason_for_inaction")
    if reason != "passed_through":
        return
    logger.info(
        "stage=%s reason=passed_through scanned=%d duration_ms=%d",
        stage_name,
        scanned,
        duration_ms,
    )


def _compute_consolidation_plan(
    episodic: list[dict],
    existing_semantics: list[dict],
    embeddings: EmbeddingEngine,
) -> dict:
    """Plan which episodic memories to consolidate into semantics."""

    def similarity_fn(emb_a, emb_b) -> float:
        if emb_a is None or emb_b is None:
            return 0.0
        return embeddings.similarity(emb_a, emb_b)

    return plan_cls_consolidation(
        episodic_memories=episodic,
        existing_semantics=existing_semantics,
        similarity_fn=similarity_fn,
        cluster_threshold=_CLUSTER_THRESHOLD,
        dedup_threshold=0.85,
        min_occurrences=_MIN_PATTERN_SIZE,
        min_sessions=2,
    )


def _create_semantic_memories(
    store: MemoryStore,
    embeddings: EmbeddingEngine,
    plan: dict,
) -> int:
    """Create new semantic memories from the consolidation plan."""
    created = 0
    for semantic in plan["new_semantics"]:
        try:
            emb = embeddings.encode(semantic["schema"])
            mem_id = store.insert_memory(
                {
                    "content": semantic["schema"],
                    "embedding": emb,
                    "tags": semantic["tags"],
                    "domain": "",
                    "directory": "",
                    "source": "cls-consolidation",
                    "importance": 0.7,
                    "surprise": 0.0,
                    "emotional_valence": 0.0,
                    "confidence": 0.8,
                    "heat": 0.6,
                    "store_type": "semantic",
                }
            )
            _link_source_memories(store, mem_id, semantic["source_memory_ids"])
            created += 1
        except Exception:
            logger.exception("Failed to create semantic memory")
    return created


def _link_source_memories(
    store: MemoryStore,
    mem_id: int,
    source_ids: list,
) -> None:
    """Link source episodic memories to the new semantic memory."""
    for source_id in source_ids:
        if source_id is None:
            continue
        try:
            store.insert_relationship(
                {
                    "source_entity_id": source_id,
                    "target_entity_id": mem_id,
                    "relationship_type": "derived_from",
                    "weight": 1.0,
                    "confidence": 0.8,
                }
            )
        except Exception:
            pass


def _discover_causal_edges(
    store: MemoryStore,
    episodic: list[dict],
) -> tuple[int, int]:
    """Discover causal edges from entity co-occurrences (PC algorithm).

    Gates on minimum signal before running the O(E²) independence tests:
    the PC algorithm needs at least `min_observations` mentions per
    entity in the sample to distinguish correlation from chance, so if
    fewer than `_MIN_ENTITIES_FOR_PC` entities clear that threshold,
    skip the analysis entirely (issue #13 Phase D).

    Returns
    -------
    (edges_stored, qualifying_count)
        edges_stored — number of causal/correlation edges persisted.
        qualifying_count — number of entities whose mention count
        reached ``_PC_MIN_OBSERVATIONS``. Surfaced for issue #14 P2
        diagnostics so the handler can distinguish "no entities mentioned
        enough" (``insufficient_pairs``) from "a few qualify but below
        ``_MIN_ENTITIES_FOR_PC``" (``no_qualifying_entities``).
    """
    try:
        all_entities = store.get_all_entities(min_heat=0.0)
        entity_names = [e["name"] for e in all_entities if e.get("name")]
        if not entity_names or not episodic:
            return 0, 0

        entity_counts = _count_entity_mentions(entity_names, episodic)
        qualifying = sum(1 for c in entity_counts.values() if c >= _PC_MIN_OBSERVATIONS)
        if qualifying < _MIN_ENTITIES_FOR_PC:
            # Insufficient signal — don't run the full O(E^2) pass.
            return 0, qualifying

        # Restrict the vocabulary to entities that meet the minimum, so
        # the co-occurrence matrix is E_qualifying^2, not E_all^2.
        active_names = [
            n for n in entity_names if entity_counts[n] >= _PC_MIN_OBSERVATIONS
        ]
        co_matrix = compute_co_occurrence_matrix(episodic, active_names)
        active_counts = {n: entity_counts[n] for n in active_names}
        edges = discover_causal_edges(
            active_names,
            co_matrix,
            active_counts,
            len(episodic),
            min_observations=_PC_MIN_OBSERVATIONS,
            independence_threshold=0.5,
        )
        return _store_causal_edges(store, all_entities, edges), qualifying
    except Exception as exc:
        logger.warning("Causal discovery failed: %s", exc, exc_info=True)
        return 0, 0


# Source: PC algorithm lower bound — need ≥3 observations per variable
# to distinguish dependence from sampling noise; need ≥5 active variables
# for the independence tests to produce any non-trivial edge.
_PC_MIN_OBSERVATIONS = 3
_MIN_ENTITIES_FOR_PC = 5


def _count_entity_mentions(
    entity_names: list[str],
    episodic: list[dict],
) -> dict[str, int]:
    """Count how many episodic memories mention each entity.

    Single pass over the episodic sample with precomputed lowercase
    content and lowercase entity names (replaces the old O(N_ep × N_ent)
    loop that called .lower() on every cell).
    """
    content_lowered = [(m.get("content") or "").lower() for m in episodic]
    counts: dict[str, int] = {}
    for name in entity_names:
        name_l = name.lower()
        counts[name] = sum(1 for c in content_lowered if name_l in c)
    return counts


def _store_causal_edges(
    store: MemoryStore,
    all_entities: list[dict],
    edges: list[dict],
) -> int:
    """Persist discovered causal edges as relationships."""
    count = 0
    for edge in edges:
        try:
            src = [e for e in all_entities if e["name"] == edge["source"]]
            tgt = [e for e in all_entities if e["name"] == edge["target"]]
            if not src or not tgt:
                continue
            store.insert_relationship(
                {
                    "source_entity_id": src[0]["id"],
                    "target_entity_id": tgt[0]["id"],
                    "relationship_type": (
                        "causes" if edge["is_directed"] else "correlates_with"
                    ),
                    "weight": edge["strength"],
                    "confidence": 0.6 if edge["is_directed"] else 0.3,
                }
            )
            count += 1
        except Exception:
            pass
    return count
