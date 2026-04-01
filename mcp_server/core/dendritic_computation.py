"""Dendritic computation — two-layer neuron model after Poirazi, Brannon & Mel (2003).

Implements the pyramidal neuron as a two-layer network:

  Layer 1 — Dendritic branch subunit function:
    s(n) = 1 / (1 + exp((3.6 - n) / 2)) + 0.30*n + 0.0114*n^2

    where n = number of active synapses on the branch.
    Half-activation at n = 3.6 synapses, slope factor 2.0.
    Sigmoid + linear + quadratic terms capture the full nonlinearity
    (NMDA plateau + cooperative unblocking + voltage-gated amplification).

  Layer 2 — Soma output nonlinearity:
    g(x) = 0.96 * x / (1 + 1509 * exp(-0.26 * x))

    where x = weighted sum of branch outputs.
    Effective threshold emerges around x ~ 20-30.

Constants 3.6, 2.0, 0.30, 0.0114, 0.96, 1509, 0.26 are all from
Poirazi P, Brannon T, Mel BW (2003) "Pyramidal Neuron as a Two-Layer
Neural Network." Neuron 37:989-999, Figure 3 and Equation fits.

Branch clustering (dendritic_clusters.py) and cluster priming are
engineering heuristics inspired by Kastellakis (2015) but not direct
implementations of any specific paper equation.

Pure business logic — no I/O.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# ── Poirazi (2003) Constants ─────────────────────────────────────────────
# All from Neuron 37:989-999, Figure 3 subunit fit and soma nonlinearity.

# Subunit sigmoid half-activation (number of active synapses)
SUBUNIT_HALF_ACTIVATION = 3.6
# Subunit sigmoid slope factor
SUBUNIT_SLOPE = 2.0
# Subunit linear coefficient
SUBUNIT_LINEAR_COEFF = 0.30
# Subunit quadratic coefficient
SUBUNIT_QUADRATIC_COEFF = 0.0114

# Soma output scaling factor
SOMA_SCALE = 0.96
# Soma exponential steepness
SOMA_STEEPNESS = 0.26
# Soma exponential offset (sets effective threshold)
SOMA_OFFSET = 1509

# ── Engineering Constants (no paper) ─────────────────────────────────────

BRANCH_ADMISSION_THRESHOLD = 0.3
MAX_BRANCH_SIZE = 15
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
        spike_count: Number of times this branch has produced high output.
    """

    branch_id: str = ""
    domain: str = ""
    memory_ids: list[int] = field(default_factory=list)
    entity_signature: set[str] = field(default_factory=set)
    tag_signature: set[str] = field(default_factory=set)
    avg_heat: float = 0.5
    plasticity: float = 1.0
    spike_count: int = 0


# ── Layer 1: Dendritic Branch Subunit — Poirazi (2003) Eq. ──────────────


def branch_subunit(
    n: float,
    *,
    half_activation: float = SUBUNIT_HALF_ACTIVATION,
    slope: float = SUBUNIT_SLOPE,
    linear_coeff: float = SUBUNIT_LINEAR_COEFF,
    quadratic_coeff: float = SUBUNIT_QUADRATIC_COEFF,
) -> float:
    """Poirazi (2003) dendritic branch subunit function.

    s(n) = 1 / (1 + exp((3.6 - n) / 2)) + 0.30*n + 0.0114*n^2

    Args:
        n: Number of active synapses on the branch. In our system this
           is the number of co-retrieved memories on the branch.
        half_activation: Sigmoid midpoint (paper: 3.6).
        slope: Sigmoid slope factor (paper: 2.0).
        linear_coeff: Linear term coefficient (paper: 0.30).
        quadratic_coeff: Quadratic term coefficient (paper: 0.0114).

    Returns:
        Branch subunit output (unbounded positive).
    """
    if n <= 0.0:
        return 0.0

    sigmoid = 1.0 / (1.0 + math.exp((half_activation - n) / slope))
    linear = linear_coeff * n
    quadratic = quadratic_coeff * n * n

    return sigmoid + linear + quadratic


# ── Layer 2: Soma Output Nonlinearity — Poirazi (2003) Eq. ──────────────


def soma_output(
    x: float,
    *,
    scale: float = SOMA_SCALE,
    steepness: float = SOMA_STEEPNESS,
    offset: float = SOMA_OFFSET,
) -> float:
    """Poirazi (2003) soma output nonlinearity.

    g(x) = 0.96 * x / (1 + 1509 * exp(-0.26 * x))

    Args:
        x: Weighted sum of branch subunit outputs.
        scale: Output scaling (paper: 0.96).
        steepness: Exponential steepness (paper: 0.26).
        offset: Exponential offset controlling threshold (paper: 1509).

    Returns:
        Soma output. Near zero for small x, rises sharply around x~28,
        approaches 0.96*x for large x.
    """
    if x <= 0.0:
        return 0.0

    # Guard against overflow in exp for very negative arguments.
    # When x is large, exp(-0.26*x) -> 0 and denominator -> 1.
    exponent = -steepness * x
    if exponent < -500.0:
        return scale * x

    return scale * x / (1.0 + offset * math.exp(exponent))


# ── Integration: Two-Layer Model ────────────────────────────────────────


def compute_dendritic_integration(
    active_count: int,
    total_count: int,
    individual_scores: list[float],
) -> tuple[float, bool]:
    """Two-layer dendritic integration after Poirazi, Brannon & Mel (2003).

    Layer 1: Each branch computes s(n) where n = active_count (number of
    co-retrieved memories on the branch). The individual_scores are used
    as synaptic weights — we weight the subunit output by the mean score
    to preserve the influence of retrieval quality.

    Layer 2: The soma applies g(x) to the weighted branch output.

    The 'spike' indicator is set when the subunit sigmoid component exceeds
    0.5 (i.e., n > half_activation = 3.6), meaning the branch has crossed
    its nonlinear threshold.

    Args:
        active_count: Number of co-activated memories on this branch.
        total_count: Total memories on the branch (unused in Poirazi model,
            retained for API compatibility).
        individual_scores: Retrieval scores of the active memories.

    Returns:
        (integrated_score, spike_occurred).
    """
    if not individual_scores:
        return 0.0, False

    n = float(active_count)

    # Layer 1: branch subunit
    subunit = branch_subunit(n)

    # Weight by mean retrieval score so higher-quality retrievals
    # produce stronger branch output.
    mean_score = sum(individual_scores) / len(individual_scores)
    weighted_branch = subunit * mean_score

    # Layer 2: soma nonlinearity
    output = soma_output(weighted_branch)

    # Spike detection: sigmoid component exceeds 0.5 (n > half-activation)
    sigmoid_component = 1.0 / (
        1.0 + math.exp((SUBUNIT_HALF_ACTIVATION - n) / SUBUNIT_SLOPE)
    )
    spiked = sigmoid_component > 0.5

    return output, spiked


# ── Cluster Priming (Engineering Heuristic) ─────────────────────────────


def compute_cluster_priming(
    retrieved_memory_id: int,
    branch: DendriticBranch,
    *,
    priming_strength: float = PRIMING_STRENGTH,
) -> dict[int, float]:
    """Associative priming from retrieving one branch member.

    Engineering heuristic, not from Poirazi (2003). Inspired by the general
    principle that co-localized synapses prime each other (Kastellakis 2015),
    but the exponential decay with list-position distance is a practical
    approximation, not a biological model.

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


# ── Branch-Specific Plasticity (Engineering Heuristic) ──────────────────


def _apply_plasticity_events(
    plasticity: float,
    ltp_occurred: bool,
    ltd_occurred: bool,
    ltp_boost: float,
    ltd_reduction: float,
) -> float:
    """Apply LTP/LTD events to a plasticity value.

    Engineering heuristic for branch-specific plasticity modulation.
    The concept of branch-specific plasticity is supported by Kastellakis
    (2015) and Losonczy et al. (2008), but the specific boost/reduction
    constants are hand-tuned, not from any paper.
    """
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

    Engineering heuristic. LTP increases plasticity; LTD decreases it.
    Passive decay toward 0.5 (homeostatic baseline).

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
