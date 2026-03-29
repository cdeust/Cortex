"""Dendritic memory clusters — branch-specific nonlinear integration.

Memories aren't stored at single synapses — they're distributed across
dendritic branches. Related synapses cluster on the same branch, enabling
nonlinear amplification (dendritic spikes). This module models:

1. **Cluster formation**: Memories are assigned to dendritic branches based
   on entity/tag similarity to existing branch members.

2. **Nonlinear amplification**: When enough synapses on a branch are
   activated simultaneously (co-retrieved), a dendritic spike occurs.

3. **Branch-specific plasticity**: LTP in one branch doesn't spread to others.

4. **Cluster retrieval boost**: Retrieving one memory from a cluster partially
   activates the whole cluster, providing associative priming.

References:
    Kastellakis G et al. (2015) Synaptic clustering within dendrites:
        an emerging theory of memory formation. Neuron 87:1144-1158
    Limbacher T, Legenstein R (2020) Emergence of stable synaptic clusters
        on dendrites. Front Comp Neurosci 14:57

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
    """Compute how well a memory fits an existing branch.

    Uses Jaccard similarity of entity and tag sets, weighted toward entities.

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
