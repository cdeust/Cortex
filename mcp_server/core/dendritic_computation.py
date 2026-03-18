"""Dendritic computation helpers — integration, plasticity, nonlinear summation.

Extracted from dendritic_clusters.py to respect the 300-line file limit.
Contains the computational core: nonlinear integration (sublinear/supralinear),
cluster priming, branch plasticity updates, statistics, and serialization.

References:
    Kastellakis G et al. (2015) Synaptic clustering within dendrites.
    Poirazi P et al. (2003) Pyramidal neuron as a two-layer neural network.

Pure business logic — no I/O.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


# ── Configuration ─────────────────────────────────────────────────────────

BRANCH_ADMISSION_THRESHOLD = 0.3
MAX_BRANCH_SIZE = 15
SPIKE_THRESHOLD = 0.4
SUBLINEAR_EXPONENT = 0.7
SUPRALINEAR_BOOST = 1.5
PRIMING_STRENGTH = 0.3


# ── Branch Model ─────────────────────────────────────────────────────────


@dataclass
class DendriticBranch:
    """A dendritic branch containing clustered memories.

    Attributes:
        branch_id: Unique identifier.
        domain: Domain this branch belongs to.
        memory_ids: IDs of memories clustered on this branch.
        entity_signature: Union of entities across branch members.
        tag_signature: Union of tags across branch members.
        avg_heat: Average heat of branch members.
        plasticity: Branch-specific plasticity level [0, 1].
        spike_count: Number of dendritic spikes this branch has fired.
    """

    branch_id: str = ""
    domain: str = ""
    memory_ids: list[int] = field(default_factory=list)
    entity_signature: set[str] = field(default_factory=set)
    tag_signature: set[str] = field(default_factory=set)
    avg_heat: float = 0.5
    plasticity: float = 1.0
    spike_count: int = 0


# ── Nonlinear Integration ────────────────────────────────────────────────


def _compute_supralinear(
    linear_sum: float,
    activation_fraction: float,
    spike_threshold: float,
    supralinear_boost: float,
) -> float:
    """Compute supralinear dendritic NMDA spike boost."""
    excess = (activation_fraction - spike_threshold) / (1.0 - spike_threshold)
    boost = 1.0 + (supralinear_boost - 1.0) * excess
    return linear_sum * boost


def _compute_sublinear(
    linear_sum: float,
    active_count: int,
    sublinear_exp: float,
) -> float:
    """Compute sublinear power-law compression."""
    if active_count <= 1:
        return linear_sum
    return linear_sum * (active_count ** (sublinear_exp - 1.0))


def compute_dendritic_integration(
    active_count: int,
    total_count: int,
    individual_scores: list[float],
    *,
    spike_threshold: float = SPIKE_THRESHOLD,
    sublinear_exp: float = SUBLINEAR_EXPONENT,
    supralinear_boost: float = SUPRALINEAR_BOOST,
) -> tuple[float, bool]:
    """Compute nonlinear dendritic integration of co-activated memories.

    Below spike threshold: sublinear (diminishing returns).
    Above spike threshold: supralinear (dendritic spike, NMDA plateau).

    Returns:
        (integrated_score, spike_occurred).
    """
    if not individual_scores or total_count == 0:
        return 0.0, False

    linear_sum = sum(individual_scores)
    activation_fraction = active_count / total_count

    if activation_fraction >= spike_threshold:
        score = _compute_supralinear(
            linear_sum,
            activation_fraction,
            spike_threshold,
            supralinear_boost,
        )
        return score, True

    score = _compute_sublinear(linear_sum, active_count, sublinear_exp)
    return score, False


def compute_cluster_priming(
    retrieved_memory_id: int,
    branch: DendriticBranch,
    *,
    priming_strength: float = PRIMING_STRENGTH,
) -> dict[int, float]:
    """Compute associative priming from retrieving one branch member.

    All other branch members get a priming boost with exponential
    decay proportional to distance on the branch.

    Returns:
        Dict of {memory_id: priming_boost} for all OTHER branch members.
    """
    if retrieved_memory_id not in branch.memory_ids:
        return {}

    idx = branch.memory_ids.index(retrieved_memory_id)
    primes: dict[int, float] = {}

    for i, mid in enumerate(branch.memory_ids):
        if mid == retrieved_memory_id:
            continue
        distance = abs(i - idx)
        prime = priming_strength * math.exp(-0.5 * distance)
        primes[mid] = round(prime, 4)

    return primes


# ── Branch-Specific Plasticity ───────────────────────────────────────────


def _apply_plasticity_events(
    plasticity: float,
    ltp_occurred: bool,
    ltd_occurred: bool,
    ltp_boost: float,
    ltd_reduction: float,
) -> float:
    """Apply LTP/LTD events to a plasticity value."""
    p = plasticity
    if ltp_occurred:
        p = min(1.0, p + ltp_boost)
    if ltd_occurred:
        p = max(0.0, p - ltd_reduction)
    return p


def update_branch_plasticity(
    branch: DendriticBranch,
    ltp_occurred: bool,
    ltd_occurred: bool,
    *,
    ltp_boost: float = 0.05,
    ltd_reduction: float = 0.03,
    decay_rate: float = 0.01,
) -> DendriticBranch:
    """Update branch-specific plasticity after learning events.

    LTP increases plasticity; LTD decreases it. Passive decay toward 0.5.

    Returns:
        Branch with updated plasticity.
    """
    p = _apply_plasticity_events(
        branch.plasticity,
        ltp_occurred,
        ltd_occurred,
        ltp_boost,
        ltd_reduction,
    )
    p += decay_rate * (0.5 - p)

    return DendriticBranch(
        branch_id=branch.branch_id,
        domain=branch.domain,
        memory_ids=branch.memory_ids,
        entity_signature=branch.entity_signature,
        tag_signature=branch.tag_signature,
        avg_heat=branch.avg_heat,
        plasticity=round(p, 4),
        spike_count=branch.spike_count + (1 if ltp_occurred else 0),
    )


# ── Metrics ──────────────────────────────────────────────────────────────


def compute_branch_statistics(branches: list[DendriticBranch]) -> dict:
    """Compute aggregate statistics across all branches."""
    if not branches:
        return {
            "total_branches": 0,
            "avg_branch_size": 0.0,
            "max_branch_size": 0,
            "avg_plasticity": 0.0,
            "total_spikes": 0,
            "orphan_branches": 0,
        }

    sizes = [len(b.memory_ids) for b in branches]
    plasticities = [b.plasticity for b in branches]

    return {
        "total_branches": len(branches),
        "avg_branch_size": round(sum(sizes) / len(sizes), 2),
        "max_branch_size": max(sizes),
        "avg_plasticity": round(sum(plasticities) / len(plasticities), 4),
        "total_spikes": sum(b.spike_count for b in branches),
        "orphan_branches": sum(1 for s in sizes if s <= 1),
    }


# ── Serialization ────────────────────────────────────────────────────────


def branch_to_dict(branch: DendriticBranch) -> dict:
    """Serialize a DendriticBranch to a plain dict."""
    return {
        "branch_id": branch.branch_id,
        "domain": branch.domain,
        "memory_ids": branch.memory_ids,
        "entity_signature": sorted(branch.entity_signature),
        "tag_signature": sorted(branch.tag_signature),
        "avg_heat": branch.avg_heat,
        "plasticity": branch.plasticity,
        "spike_count": branch.spike_count,
    }


def branch_from_dict(data: dict) -> DendriticBranch:
    """Deserialize a plain dict to a DendriticBranch."""
    return DendriticBranch(
        branch_id=data.get("branch_id", ""),
        domain=data.get("domain", ""),
        memory_ids=data.get("memory_ids", []),
        entity_signature=set(data.get("entity_signature", [])),
        tag_signature=set(data.get("tag_signature", [])),
        avg_heat=data.get("avg_heat", 0.5),
        plasticity=data.get("plasticity", 1.0),
        spike_count=data.get("spike_count", 0),
    )
