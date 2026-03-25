"""Retrieval signal computation for HDC, Hopfield, SR, and Spreading Activation.

Spreading activation and SR co-access use PL/pgSQL stored procedures
for server-side computation. Hopfield and HDC stay client-side (numpy).

Pure business logic (takes store/embeddings as parameters -- no globals).
"""

from __future__ import annotations

from typing import Any

from mcp_server.core import hopfield
from mcp_server.core.hdc_encoder import compute_hdc_scores
from mcp_server.core.cognitive_map import compute_sr_scores
from mcp_server.core.query_decomposition import extract_query_entities


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
    """Hopfield network + HDC signals.

    Hopfield: uses get_hot_embeddings() PL/pgSQL for efficient fetch,
    then client-side softmax attention (numpy).
    HDC: fully client-side bipolar vector encoding.
    """
    hop: list[tuple[int, float]] = []
    hdc: list[tuple[int, float]] = []
    if q_emb:
        try:
            # Use PG-side batch embedding fetch (single round trip)
            pairs = store.get_hot_embeddings(
                min_heat=min_heat, limit=pool * 2
            )
            emb_pairs = [(mid, emb) for mid, emb, _ in pairs if emb]
            if emb_pairs:
                mat, ids = hopfield.build_pattern_matrix(
                    emb_pairs, embeddings.dimensions
                )
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
    """Successor Representation + Spreading Activation signals.

    SA: single PL/pgSQL call (spread_activation_memories).
    SR: PG-side co-access fetch + client-side scoring.
    """
    sr = _compute_sr(store, vec_results, pool)
    sa = _compute_sa(query, store, min_heat, settings)
    return sr, sa


def _compute_sr(
    store: Any,
    vec_results: list[tuple[int, float]],
    pool: int,
) -> list[tuple[int, float]]:
    """Successor Representation from PG-side temporal co-access."""
    try:
        if not vec_results:
            return []
        # Use PG-side co-access query (single round trip)
        pairs = store.get_temporal_co_access(
            window_hours=2.0, min_access=1, limit=100
        )
        if not pairs:
            return []
        # Build SR graph from PG co-access pairs
        g: dict[int, dict[int, float]] = {}
        for mem_a, mem_b, proximity in pairs:
            g.setdefault(mem_a, {})[mem_b] = proximity
            g.setdefault(mem_b, {})[mem_a] = proximity * 0.45  # back-link weaker
        seeds = [m for m, _ in vec_results[:3]]
        return compute_sr_scores(seeds, g, top_k=pool)
    except Exception:
        return []


def _compute_sa(
    query: str,
    store: Any,
    min_heat: float,
    settings: Any,
) -> list[tuple[int, float]]:
    """Spreading Activation via PL/pgSQL spread_activation_memories.

    Single server-side call replacing:
      1. get_all_entities
      2. get_all_relationships
      3. build_entity_graph + resolve_seed_entities + spread_activation
      4. N × get_memories_mentioning_entity
    """
    try:
        terms = list(
            set(
                extract_query_entities(query) + [w for w in query.split() if len(w) > 2]
            )
        )
        if not terms:
            return []
        return store.spread_activation_memories(
            query_terms=terms,
            decay=settings.SA_DECAY,
            threshold=settings.SA_THRESHOLD,
            max_depth=settings.SA_MAX_DEPTH,
            max_results=settings.SA_MAX_NODES,
            min_heat=min_heat,
        )
    except Exception:
        return []
