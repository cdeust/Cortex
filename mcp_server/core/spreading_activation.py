"""Spreading activation over the entity-relationship graph.

Implements Collins & Loftus (1975) semantic priming: when a node is activated
(queried), activation propagates along edges to connected nodes with exponential
decay by distance. Nodes receiving convergent activation from multiple sources
get boosted, enabling multi-hop associative retrieval.

This becomes Signal #7 in the WRRF retrieval fusion pipeline.

Pure business logic — no I/O.
"""

from __future__ import annotations

# ── Defaults ──────────────────────────────────────────────────────────────

_DEFAULT_DECAY: float = 0.65
_DEFAULT_THRESHOLD: float = 0.1
_DEFAULT_MAX_DEPTH: int = 3
_DEFAULT_MAX_NODES: int = 50

# Type alias: adjacency list — entity_id → [(neighbor_id, edge_weight)]
EntityGraph = dict[int, list[tuple[int, float]]]


def _initialize_seeds(
    graph: EntityGraph,
    seed_entity_ids: list[int],
    initial_activation: float,
) -> dict[int, float]:
    """Set initial activation for seed entities present in the graph."""
    return {eid: initial_activation for eid in seed_entity_ids if eid in graph}


def _propagate_one_hop(
    graph: EntityGraph,
    activation: dict[int, float],
    frontier: set[int],
    seed_set: set[int],
    decay: float,
    threshold: float,
) -> set[int]:
    """Propagate activation one BFS hop, returning the next frontier."""
    next_frontier: set[int] = set()
    half_threshold = threshold * 0.5

    for node_id in frontier:
        node_act = activation.get(node_id, 0.0)
        if node_act < threshold:
            continue
        for neighbor_id, edge_weight in graph.get(node_id, []):
            spread = node_act * edge_weight * decay
            if spread < half_threshold:
                continue
            activation[neighbor_id] = activation.get(neighbor_id, 0.0) + spread
            next_frontier.add(neighbor_id)

    return {
        nid
        for nid in next_frontier
        if activation.get(nid, 0.0) >= threshold and nid not in seed_set
    }


def _cap_activations(
    activation: dict[int, float],
    max_nodes: int,
) -> dict[int, float]:
    """Keep only the top max_nodes entries by activation score."""
    if len(activation) <= max_nodes:
        return activation
    sorted_items = sorted(activation.items(), key=lambda x: x[1], reverse=True)
    return dict(sorted_items[:max_nodes])


def spread_activation(
    graph: EntityGraph,
    seed_entity_ids: list[int],
    initial_activation: float = 1.0,
    decay: float = _DEFAULT_DECAY,
    threshold: float = _DEFAULT_THRESHOLD,
    max_depth: int = _DEFAULT_MAX_DEPTH,
    max_nodes: int = _DEFAULT_MAX_NODES,
) -> dict[int, float]:
    """Run spreading activation from seed entities over an entity graph.

    Algorithm (Collins & Loftus 1975, adapted):
      1. Initialize activation[seed] = initial_activation for each seed.
      2. BFS by depth -- propagate to neighbors with convergent summation.
      3. Stop at max_depth or when no nodes exceed threshold.
      4. Cap total activated nodes at max_nodes (keep top by activation).

    Returns dict of {entity_id: activation_score} for all reached entities.
    """
    activation = _initialize_seeds(graph, seed_entity_ids, initial_activation)
    if not activation:
        return {}

    seed_set = set(seed_entity_ids)
    frontier = set(activation.keys())

    for _depth in range(max_depth):
        frontier = _propagate_one_hop(
            graph, activation, frontier, seed_set, decay, threshold
        )
        if not frontier:
            break

    return _cap_activations(activation, max_nodes)


def map_entity_activation_to_memories(
    entity_activations: dict[int, float],
    entity_to_memory_ids: dict[int, list[int]],
) -> list[tuple[int, float]]:
    """Map entity activation scores to memory scores.

    A memory's score = max activation of any entity it mentions.
    Using max (not sum) avoids over-boosting memories that happen to
    mention many low-activation entities.

    Parameters
    ----------
    entity_activations : {entity_id: activation} from spread_activation.
    entity_to_memory_ids : {entity_id: [memory_id, ...]} mapping.

    Returns
    -------
    List of (memory_id, score) sorted descending by score.
    """
    memory_scores: dict[int, float] = {}

    for entity_id, activation in entity_activations.items():
        for mem_id in entity_to_memory_ids.get(entity_id, []):
            if activation > memory_scores.get(mem_id, 0.0):
                memory_scores[mem_id] = activation

    return sorted(memory_scores.items(), key=lambda x: x[1], reverse=True)


def resolve_seed_entities(
    query_terms: list[str],
    entity_index: dict[str, int],
) -> list[int]:
    """Resolve query terms to entity IDs using case-insensitive matching.

    Parameters
    ----------
    query_terms : Keywords/entity names extracted from the query.
    entity_index : {lowercase_entity_name: entity_id} lookup.

    Returns
    -------
    List of matched entity IDs (deduplicated).
    """
    seen: set[int] = set()
    result: list[int] = []
    for term in query_terms:
        eid = entity_index.get(term.lower())
        if eid is not None and eid not in seen:
            seen.add(eid)
            result.append(eid)
    return result


def _index_entities(
    entities: list[dict],
    min_heat: float,
) -> tuple[set[int], dict[str, int]]:
    """Build entity ID set and lowercase name index, filtering by min_heat."""
    entity_ids: set[int] = set()
    name_index: dict[str, int] = {}
    for ent in entities:
        if ent.get("heat", 0) >= min_heat:
            eid = ent["id"]
            entity_ids.add(eid)
            name = ent.get("name", "")
            if name:
                name_index[name.lower()] = eid
    return entity_ids, name_index


def _build_adjacency(
    relationships: list[dict],
    entity_ids: set[int],
) -> EntityGraph:
    """Build bidirectional adjacency list from relationships."""
    graph: EntityGraph = {}
    for rel in relationships:
        src = rel.get("source_entity_id")
        tgt = rel.get("target_entity_id")
        if src not in entity_ids or tgt not in entity_ids:
            continue
        edge_weight = rel.get("weight", 1.0) * rel.get("confidence", 1.0)
        graph.setdefault(src, []).append((tgt, edge_weight))
        graph.setdefault(tgt, []).append((src, edge_weight))
    return graph


def build_entity_graph(
    entities: list[dict],
    relationships: list[dict],
    min_heat: float = 0.0,
) -> tuple[EntityGraph, dict[str, int]]:
    """Build an adjacency list and name index from raw entity/relationship data.

    This is a pure helper — takes pre-loaded data, no I/O.

    Returns
    -------
    - graph: {entity_id: [(neighbor_id, edge_weight), ...]}
    - name_index: {lowercase_name: entity_id}
    """
    entity_ids, name_index = _index_entities(entities, min_heat)
    graph = _build_adjacency(relationships, entity_ids)
    return graph, name_index
