"""Causal graph -- PC-algorithm causal edge discovery.

Structure is learned by the faithful PC algorithm (Spirtes & Glymour 1991;
Spirtes, Glymour & Scheines 2000) in ``causal_pc``: a G² conditional-
independence test over binary entity-presence data drives skeleton learning
with growing conditioning sets, followed by v-structure (collider)
orientation. Remaining undirected edges are oriented from temporal
precedence used as PC background knowledge (a standard tiered/temporal-prior
extension; Spirtes et al. 2000 §6.6) — never overriding a v-structure.

PC determines the *graph structure* (which edges exist and their direction).
Each surviving edge is additionally annotated with a pointwise-mutual-
information *effect size* purely for downstream ranking — PMI is not part of
the structure-learning decision.

Adjacency representation, no networkx. Pure business logic -- no I/O.
"""

from __future__ import annotations

import math
from typing import Any

from mcp_server.core.causal_pc import orient_v_structures, pc_skeleton


def build_presence(
    memories: list[dict[str, Any]],
    entity_names: list[str],
) -> list[frozenset[str]]:
    """Binary presence sample: one frozenset of present entities per memory.

    This is the observation matrix the PC G² test operates on — each memory
    is an i.i.d. sample, each entity a binary variable.
    """
    lowered = [(e, e.lower()) for e in entity_names]
    samples: list[frozenset[str]] = []
    for mem in memories:
        content = (mem.get("content") or "").lower()
        samples.append(frozenset(name for name, low in lowered if low in content))
    return samples


def _pmi_effect_size(pair_count: int, a_count: int, b_count: int, total: int) -> float:
    """Pointwise mutual information log₂(p_ab / p_a·p_b) — edge effect size.

    Used only to annotate the *strength* of an edge that PC has already
    decided to keep; it plays no role in the structure-learning test.
    """
    if total == 0 or a_count == 0 or b_count == 0 or pair_count == 0:
        return 0.0
    p_ab = pair_count / total
    expected = (a_count / total) * (b_count / total)
    if expected == 0:
        return 0.0
    return round(math.log2(p_ab / expected), 4)


def compute_temporal_precedence(
    entity_first_seen: dict[str, str],
    entity_a: str,
    entity_b: str,
) -> str | None:
    """Determine temporal ordering between two entities.

    Returns:
      - "a_before_b" if A consistently appears before B
      - "b_before_a" if B consistently appears before A
      - None if no clear ordering
    """
    time_a = entity_first_seen.get(entity_a)
    time_b = entity_first_seen.get(entity_b)

    if time_a is None or time_b is None:
        return None

    if time_a < time_b:
        return "a_before_b"
    elif time_b < time_a:
        return "b_before_a"
    return None


def _entity_and_pair_counts(
    presence: list[frozenset[str]],
    entity_names: list[str],
) -> tuple[dict[str, int], dict[frozenset[str], int]]:
    """Marginal mention counts and pairwise co-occurrence counts from presence."""
    names = set(entity_names)
    counts: dict[str, int] = dict.fromkeys(entity_names, 0)
    pairs: dict[frozenset[str], int] = {}
    for sample in presence:
        present = [e for e in sample if e in names]
        for e in present:
            counts[e] += 1
        for i in range(len(present)):
            for j in range(i + 1, len(present)):
                key = frozenset((present[i], present[j]))
                pairs[key] = pairs.get(key, 0) + 1
    return counts, pairs


def _resolve_direction(
    a: str,
    b: str,
    directed: set[tuple[str, str]],
    entity_first_seen: dict[str, str],
) -> tuple[str, str, bool]:
    """Pick (source, target, is_directed) for an undirected skeleton edge.

    PC v-structure orientation wins; otherwise temporal precedence is applied
    as background knowledge. A conflicting bidirected mark stays undirected.
    """
    fwd, rev = (a, b) in directed, (b, a) in directed
    if fwd and not rev:
        return a, b, True
    if rev and not fwd:
        return b, a, True
    if not fwd and not rev:
        precedence = compute_temporal_precedence(entity_first_seen, a, b)
        if precedence == "a_before_b":
            return a, b, True
        if precedence == "b_before_a":
            return b, a, True
    return a, b, False


def discover_causal_edges(
    entity_names: list[str],
    presence: list[frozenset[str]],
    *,
    entity_first_seen: dict[str, str] | None = None,
    # PC test significance level (Spirtes et al. 2000 use α as the CI-test
    # level; 0.05 is the conventional default) and the conditioning-set size
    # cap (standard PC tractability bound, e.g. causal-learn's default).
    alpha: float = 0.05,
    max_cond_size: int = 3,
    # Sparse-noise floor: drop edges with fewer than this many co-occurrences
    # (engineering guard; PC's G² test already suppresses low-count pairs).
    min_observations: int = 3,
) -> list[dict[str, Any]]:
    """Discover causal edges with the PC algorithm (see module docstring).

    Algorithm (Spirtes & Glymour 1991):
      1. PC skeleton — G² conditional-independence tests with growing
         conditioning sets remove edges between independent entities.
      2. v-structure orientation — unshielded colliders X→Z←Y.
      3. Temporal precedence orients any edge left undirected (background
         knowledge), never overriding a v-structure.

    Returns list of edges: {source, target, strength, is_directed, evidence},
    where ``strength`` is a PMI effect size (annotation only) and ``evidence``
    is the raw co-occurrence count.
    """
    if not entity_names or not presence:
        return []

    counts, pairs = _entity_and_pair_counts(presence, entity_names)
    total = len(presence)
    skeleton, sepsets = pc_skeleton(entity_names, presence, alpha, max_cond_size)
    directed = orient_v_structures(entity_names, skeleton, sepsets)
    first_seen = entity_first_seen or {}

    causal_edges: list[dict[str, Any]] = []
    for edge in skeleton:
        a, b = sorted(edge)
        evidence = pairs.get(edge, 0)
        if evidence < min_observations:
            continue
        source, target, is_directed = _resolve_direction(a, b, directed, first_seen)
        causal_edges.append(
            {
                "source": source,
                "target": target,
                "strength": _pmi_effect_size(
                    evidence, counts.get(a, 0), counts.get(b, 0), total
                ),
                "is_directed": is_directed,
                "evidence": evidence,
            }
        )

    causal_edges.sort(key=lambda e: e["strength"], reverse=True)
    return causal_edges


def _build_directed_adjacency(edges: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Build adjacency list from directed edges only."""
    adj: dict[str, list[str]] = {}
    for edge in edges:
        if edge.get("is_directed"):
            adj.setdefault(edge["source"], []).append(edge["target"])
    return adj


def find_causal_chain(
    edges: list[dict[str, Any]],
    start: str,
    max_depth: int = 5,
) -> list[list[str]]:
    """Find causal chains starting from a given entity.

    Returns list of paths: [[start, step1, step2, ...], ...].
    """
    adj = _build_directed_adjacency(edges)

    if start not in adj:
        return []

    paths: list[list[str]] = []
    stack: list[tuple[str, list[str]]] = [(start, [start])]

    while stack:
        node, path = stack.pop()
        if len(path) > max_depth:
            continue

        neighbors = adj.get(node, [])
        if not neighbors and len(path) > 1:
            paths.append(path)
            continue

        extended = False
        for neighbor in neighbors:
            if neighbor not in path:  # Avoid cycles
                stack.append((neighbor, path + [neighbor]))
                extended = True

        if not extended and len(path) > 1:
            paths.append(path)

    return paths


def find_common_causes(
    edges: list[dict[str, Any]],
    entity_a: str,
    entity_b: str,
) -> list[str]:
    """Find common causes of two entities (fork structures)."""
    # Build reverse adjacency (target → sources)
    reverse_adj: dict[str, set[str]] = {}
    for edge in edges:
        if edge.get("is_directed"):
            reverse_adj.setdefault(edge["target"], set()).add(edge["source"])

    causes_a = reverse_adj.get(entity_a, set())
    causes_b = reverse_adj.get(entity_b, set())

    return sorted(causes_a & causes_b)
