"""Tripartite synapse — astrocyte-mediated synaptic modulation.

Owns AstrocyteTerritory, territory update orchestration, and serialization.
Calcium dynamics, D-serine modulation, and metabolic computations live in
tripartite_calcium.py. All public symbols are re-exported here for backward
compatibility.

Key mechanisms:
  1. Territory coverage: each astrocyte covers a cluster of memories.
  2. Calcium dynamics: three regimes (quiescent, facilitation, depression).
  3. Cross-synapse coordination via calcium waves.
  4. Metabolic gating: active territories get more resources.

References:
    Perea G, Navarrete M, Araque A (2009) Tripartite synapses: astrocytes
        process and control synaptic information. Trends Neurosci 32:421-431
    Cells/MDPI (2025) Astrocyte-mediated plasticity: multi-scale mechanisms
        linking synaptic dynamics to learning and memory.

Pure business logic — no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mcp_server.core.tripartite_calcium import (
    METABOLIC_BASELINE,
    classify_calcium_regime,
    compute_calcium_decay,
    compute_calcium_rise,
    compute_metabolic_rate,
)

__all__ = [
    "AstrocyteTerritory",
    "classify_calcium_regime",
    "compute_calcium_decay",
    "compute_calcium_rise",
    "compute_metabolic_rate",
    "territory_from_dict",
    "territory_to_dict",
    "update_territory",
]


# ── Territory Model ──────────────────────────────────────────────────────


@dataclass
class AstrocyteTerritory:
    """An astrocyte territory covering a cluster of memories.

    Maps to an L1 fractal cluster. One astrocyte per cluster.
    """

    territory_id: str = ""
    domain: str = ""
    calcium: float = 0.0
    metabolic_rate: float = METABOLIC_BASELINE
    memory_ids: list[int] = field(default_factory=list)
    total_activity: float = 0.0
    d_serine_active: bool = False
    glutamate_active: bool = False


# ── Territory Management ─────────────────────────────────────────────────


def update_territory(
    territory: AstrocyteTerritory,
    synaptic_events: int,
    hours_elapsed: float,
) -> AstrocyteTerritory:
    """Update a territory's state after a period of activity.

    Returns:
        New AstrocyteTerritory (original not mutated).
    """
    ca = compute_calcium_rise(territory.calcium, synaptic_events)
    ca = compute_calcium_decay(ca, hours_elapsed)

    new_activity = territory.total_activity + synaptic_events
    metabolic = compute_metabolic_rate(
        new_activity,
        hours_elapsed + 1.0,
    )

    regime = classify_calcium_regime(ca)

    return AstrocyteTerritory(
        territory_id=territory.territory_id,
        domain=territory.domain,
        calcium=round(ca, 6),
        metabolic_rate=round(metabolic, 4),
        memory_ids=territory.memory_ids,
        total_activity=new_activity,
        d_serine_active=(regime == "facilitation"),
        glutamate_active=(regime == "depression"),
    )


# ── Serialization ─────────────────────────────────────────────────────────


def territory_to_dict(territory: AstrocyteTerritory) -> dict:
    """Serialize territory to JSON-compatible dict."""
    return {
        "territory_id": territory.territory_id,
        "domain": territory.domain,
        "calcium": territory.calcium,
        "metabolic_rate": territory.metabolic_rate,
        "memory_ids": territory.memory_ids,
        "total_activity": territory.total_activity,
        "d_serine_active": territory.d_serine_active,
        "glutamate_active": territory.glutamate_active,
    }


def territory_from_dict(data: dict) -> AstrocyteTerritory:
    """Deserialize territory from dict."""
    return AstrocyteTerritory(
        territory_id=data.get("territory_id", ""),
        domain=data.get("domain", ""),
        calcium=data.get("calcium", 0.0),
        metabolic_rate=data.get("metabolic_rate", METABOLIC_BASELINE),
        memory_ids=data.get("memory_ids", []),
        total_activity=data.get("total_activity", 0.0),
        d_serine_active=data.get("d_serine_active", False),
        glutamate_active=data.get("glutamate_active", False),
    )
