"""Dendritic memory clusters — semantic-similarity-based memory grouping.

Groups memories onto "branches" based on entity/tag Jaccard similarity.
Co-clustered memories benefit from nonlinear amplification during retrieval
(see dendritic_computation.py).

What Kastellakis (2015) describes:
  Related synapses physically co-localize on the same dendritic branch.
  When co-activated, NMDA-dependent nonlinear events (dendritic spikes)
  amplify the signal supralinearly. Clustering is driven by spatiotemporal
  coincidence of synaptic inputs, not semantic similarity.

What this code does:
  Assigns memories to branches via Jaccard similarity of entity/tag sets
  (0.7 entity + 0.3 tag weighting). This is a semantic grouping heuristic
  that uses dendritic terminology metaphorically. The branch admission
  threshold (0.3), max branch size (15), and entity/tag weights are all
  hand-tuned engineering choices.

The metaphor is useful: grouping related memories enables the nonlinear
retrieval boost in dendritic_computation.py (which more closely follows
Poirazi 2003's two-layer neuron model). But the assignment mechanism is
not the biological one.

Pure business logic — no I/O.
"""

from __future__ import annotations

from mcp_server.core.dendritic_computation import (
    BRANCH_ADMISSION_THRESHOLD as _BRANCH_ADMISSION_THRESHOLD,
)
from mcp_server.core.dendritic_computation import (
    MAX_BRANCH_SIZE as _MAX_BRANCH_SIZE,
)
from mcp_server.core.dendritic_computation import (
    DendriticBranch,
)
from mcp_server.shared.similarity import jaccard_similarity

# ── Branch Assignment ────────────────────────────────────────────────────


def compute_branch_affinity(
    memory_entities: set[str],
    memory_tags: set[str],
    branch: DendriticBranch,
) -> float:
    """Weighted Jaccard similarity (0.7 entity + 0.3 tag). Heuristic — no paper.

    In biology, dendritic clustering is driven by spatiotemporal coincidence,
    not semantic similarity. This is a practical engineering proxy.

    Returns:
        Affinity score [0, 1].
    """
    entity_sim = (
        jaccard_similarity(memory_entities, branch.entity_signature)
        if (memory_entities or branch.entity_signature)
        else 0.0
    )
    tag_sim = (
        jaccard_similarity(memory_tags, branch.tag_signature)
        if (memory_tags or branch.tag_signature)
        else 0.0
    )
    return entity_sim * 0.7 + tag_sim * 0.3


def find_best_branch(
    memory_entities: set[str],
    memory_tags: set[str],
    branches: list[DendriticBranch],
    *,
    threshold: float = _BRANCH_ADMISSION_THRESHOLD,
    max_size: int = _MAX_BRANCH_SIZE,
) -> tuple[DendriticBranch | None, float]:
    """Find the best branch for a new memory, or None if no match.

    Returns:
        (best_branch, affinity_score). None if no branch qualifies.
    """
    from mcp_server.core.ablation import Mechanism, is_mechanism_disabled

    if is_mechanism_disabled(Mechanism.DENDRITIC_CLUSTERS):
        # No-op: no branch-based modulation; no cluster match.
        return None, 0.0

    best: DendriticBranch | None = None
    best_score = 0.0

    for branch in branches:
        if len(branch.memory_ids) >= max_size:
            continue
        score = compute_branch_affinity(memory_entities, memory_tags, branch)
        if score > best_score and score >= threshold:
            best_score = score
            best = branch

    return best, best_score


def add_memory_to_branch(
    branch: DendriticBranch,
    memory_id: int,
    memory_entities: set[str],
    memory_tags: set[str],
    memory_heat: float,
) -> DendriticBranch:
    """Add a memory to a branch, updating its signatures.

    Returns new branch (original not mutated).
    """
    new_ids = branch.memory_ids + [memory_id]
    new_entities = branch.entity_signature | memory_entities
    new_tags = branch.tag_signature | memory_tags

    n = len(new_ids)
    new_avg = ((branch.avg_heat * (n - 1)) + memory_heat) / n

    return DendriticBranch(
        branch_id=branch.branch_id,
        domain=branch.domain,
        memory_ids=new_ids,
        entity_signature=new_entities,
        tag_signature=new_tags,
        avg_heat=round(new_avg, 4),
        plasticity=branch.plasticity,
        spike_count=branch.spike_count,
    )


def create_branch(
    branch_id: str,
    domain: str,
    memory_id: int,
    memory_entities: set[str],
    memory_tags: set[str],
    memory_heat: float,
) -> DendriticBranch:
    """Create a new branch with one founding memory."""
    return DendriticBranch(
        branch_id=branch_id,
        domain=domain,
        memory_ids=[memory_id],
        entity_signature=set(memory_entities),
        tag_signature=set(memory_tags),
        avg_heat=memory_heat,
    )
