"""Retrieval signal computation for HDC, Hopfield, SR, and Spreading Activation.

These are the "heavy" signals that require entity graphs, co-access data,
or pattern matrices. Separated from the handler for clean architecture.

Pure business logic (takes store/embeddings as parameters -- no globals).
"""

from __future__ import annotations

from typing import Any

from mcp_server.core import hopfield
from mcp_server.core.hdc_encoder import compute_hdc_scores
from mcp_server.core.cognitive_map import build_temporal_co_access, compute_sr_scores
from mcp_server.core.query_decomposition import extract_query_entities
from mcp_server.core.spreading_activation import (
    spread_activation,
    map_entity_activation_to_memories,
    resolve_seed_entities,
    build_entity_graph,
)


def compute_hopfield_hdc(
    query: str,
    q_emb: Any,
    store: Any,
    embeddings: Any,
    hot_mems: list[dict],
    settings: Any,
    pool: int,
    min_heat: float,
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Hopfield network + HDC signals."""
    hop: list[tuple[int, float]] = []
    hdc: list[tuple[int, float]] = []
    if q_emb:
        try:
            pairs = [
                (m["id"], m["embedding"])
                for m in store.get_all_memories_with_embeddings()
                if m.get("embedding") and m.get("heat", 0) >= min_heat
            ]
            if pairs:
                mat, ids = hopfield.build_pattern_matrix(pairs, embeddings.dimensions)
                if mat.size > 0:
                    hop = hopfield.retrieve(
                        q_emb, mat, ids, beta=settings.HOPFIELD_BETA, top_k=pool
                    )
        except Exception:
            pass
    try:
        if hot_mems:
            raw = compute_hdc_scores(
                query,
                [(m["id"], m.get("content", "")) for m in hot_mems],
                threshold=0.05,
            )
            hdc = [(mid, (s + 1.0) / 2.0) for mid, s in raw]
    except Exception:
        pass
    return hop, hdc


def compute_graph_signals(
    query: str,
    store: Any,
    vec_results: list[tuple[int, float]],
    min_heat: float,
    settings: Any,
    pool: int,
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Successor Representation + Spreading Activation signals."""
    sr = _compute_sr(store, vec_results, pool)
    sa = _compute_sa(query, store, min_heat, settings)
    return sr, sa


def _compute_sr(
    store: Any,
    vec_results: list[tuple[int, float]],
    pool: int,
) -> list[tuple[int, float]]:
    """Successor Representation from co-access patterns."""
    try:
        recent = store.get_recently_accessed_memories(limit=100, min_access_count=1)
        if recent and vec_results:
            g = build_temporal_co_access(recent, window_hours=2.0)
            return compute_sr_scores([m for m, _ in vec_results[:3]], g, top_k=pool)
    except Exception:
        pass
    return []


def _build_entity_to_memory_map(
    store: Any, acts: dict[int, float]
) -> dict[int, list[int]]:
    """Map activated entity IDs to their associated memory IDs."""
    e2m: dict[int, list[int]] = {}
    for eid in acts:
        ent = store.get_entity_by_id(eid)
        if ent:
            e2m[eid] = [
                m["id"]
                for m in store.get_memories_mentioning_entity(ent["name"], limit=10)
            ]
    return e2m


def _compute_sa(
    query: str,
    store: Any,
    min_heat: float,
    settings: Any,
) -> list[tuple[int, float]]:
    """Spreading Activation over entity graph (Collins & Loftus 1975)."""
    try:
        terms = list(
            set(
                extract_query_entities(query) + [w for w in query.split() if len(w) > 2]
            )
        )
        if not terms:
            return []
        ents = store.get_all_entities(min_heat=min_heat)
        rels = store.get_all_relationships()
        if not (ents and rels):
            return []
        g, idx = build_entity_graph(ents, rels, min_heat=min_heat)
        seeds = resolve_seed_entities(terms, idx)
        if not (seeds and g):
            return []
        acts = spread_activation(
            g,
            seeds,
            decay=settings.SA_DECAY,
            threshold=settings.SA_THRESHOLD,
            max_depth=settings.SA_MAX_DEPTH,
            max_nodes=settings.SA_MAX_NODES,
        )
        return map_entity_activation_to_memories(
            acts, _build_entity_to_memory_map(store, acts)
        )
    except Exception:
        return []
