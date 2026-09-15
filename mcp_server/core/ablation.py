"""Ablation framework -- lesion study simulator for Cortex mechanisms.

source: ADR-0095"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from mcp_server.core.environment import read_environment_variable


def is_mechanism_disabled(mechanism: "Mechanism | str") -> bool:
    """True iff CORTEX_ABLATE_<NAME>=1 is set for this mechanism.

    source: ADR-0095

    Reads the injected environment reader (mcp_server.core.environment) on
    every call, never memoized. Raises RuntimeError if no composition root
    configured the reader yet -- see that module's docstring for why a
    silent "treat as unset" default is not acceptable here (it would make
    ablation studies silently measure the un-ablated system).

    source: ADR-0095

    Accepts either a Mechanism enum (uses .name -> e.g. "OSCILLATORY_CLOCK")
    or a string (upper-cased, hyphens normalized).
    """
    if isinstance(mechanism, Mechanism):
        name = mechanism.name
    else:
        name = str(mechanism).upper().replace("-", "_")
    return read_environment_variable(f"CORTEX_ABLATE_{name}") == "1"


class Mechanism(Enum):
    """Enumerate ablatable mechanisms and retrieval or maintenance flags.

    source: ADR-0095
    """

    OSCILLATORY_CLOCK = "oscillatory_clock"
    CASCADE = "consolidation_cascade"
    PREDICTIVE_CODING = "hierarchical_predictive_coding"
    NEUROMODULATION = "coupled_neuromodulation"
    PATTERN_SEPARATION = "pattern_separation"
    SCHEMA_ENGINE = "schema_engine"
    TRIPARTITE_SYNAPSE = "tripartite_synapse"
    INTERFERENCE = "interference_management"
    HOMEOSTATIC_PLASTICITY = "homeostatic_plasticity"
    SYNAPTIC_PLASTICITY = "synaptic_plasticity"
    SYNAPTIC_TAGGING = "synaptic_tagging"
    EMOTIONAL_TAGGING = "emotional_tagging"
    MICROGLIAL_PRUNING = "microglial_pruning"
    SPREADING_ACTIVATION = "spreading_activation"
    ENGRAM_ALLOCATION = "engram_allocation"
    RECONSOLIDATION = "reconsolidation"
    DENDRITIC_CLUSTERS = "dendritic_clusters"
    TWO_STAGE_MODEL = "two_stage_model"
    HOPFIELD = "hopfield_network"
    HDC = "hyperdimensional_computing"
    SURPRISE_MOMENTUM = "surprise_momentum"
    ADAPTIVE_DECAY = "adaptive_decay"
    CO_ACTIVATION = "co_activation"
    EMOTIONAL_RETRIEVAL = "emotional_retrieval"
    EMOTIONAL_DECAY = "emotional_decay"
    MOOD_CONGRUENT_RERANK = "mood_congruent_rerank"
    ENTITY_DEDUP = "entity_dedup"
    COMPRESSION = "compression"
    ACTIVE_FORGETTING = "active_forgetting"
    VALUE_PRIORITY = "value_priority"
    HABITUATION = "habituation"
    CONFLICT_MONITOR = "conflict_monitor"
    DUAL_PROCESS = "dual_process"
    SLEEP_PHASES = "sleep_phases"
    TARGETED_REACTIVATION = "targeted_reactivation"
    EXTINCTION = "extinction"
    STRESS_MODULATION = "stress_modulation"
    GOAL_MAINTENANCE = "goal_maintenance"
    FORWARD_MODEL = "forward_model"
    CONFABULATION_GATE = "confabulation_gate"
    ATTENTIONAL_CONTROL = "attentional_control"


@dataclass
class AblationConfig:
    """Configuration specifying which mechanisms are enabled/disabled.

    source: ADR-0095"""

    disabled: set[str] = field(default_factory=set)


def ablation_config_is_enabled(
    config: "AblationConfig", mechanism: Mechanism | str
) -> bool:
    """Check if a mechanism is enabled."""
    name = mechanism.value if isinstance(mechanism, Mechanism) else mechanism
    return name not in config.disabled


def ablation_config_disable(
    config: "AblationConfig", mechanism: Mechanism | str
) -> "AblationConfig":
    """Return new config with mechanism disabled."""
    name = mechanism.value if isinstance(mechanism, Mechanism) else mechanism
    return AblationConfig(disabled=config.disabled | {name})


def ablation_config_enable(
    config: "AblationConfig", mechanism: Mechanism | str
) -> "AblationConfig":
    """Return new config with mechanism enabled."""
    name = mechanism.value if isinstance(mechanism, Mechanism) else mechanism
    return AblationConfig(disabled=config.disabled - {name})


def ablation_config_disable_all_except(
    config: "AblationConfig", *mechanisms: Mechanism
) -> "AblationConfig":
    """Disable all mechanisms except the specified ones.

    source: ADR-0095"""
    keep = {m.value for m in mechanisms}
    all_mechs = {m.value for m in Mechanism}
    return AblationConfig(disabled=all_mechs - keep)


# -- Ablation Results ---------------------------------------------------------


@dataclass
class AblationResult:
    """Result of comparing baseline vs ablation condition."""

    mechanism: str
    baseline_metrics: dict[str, float] = field(default_factory=dict)
    ablation_metrics: dict[str, float] = field(default_factory=dict)
    deltas: dict[str, float] = field(default_factory=dict)
    impact_score: float = 0.0
    interpretation: str = ""


def compute_ablation_deltas(
    baseline: dict[str, float],
    ablation: dict[str, float],
) -> dict[str, float]:
    """Compute signed differences between baseline and ablation metrics."""
    deltas: dict[str, float] = {}
    for key in set(baseline) | set(ablation):
        b = baseline.get(key, 0.0)
        a = ablation.get(key, 0.0)
        deltas[key] = round(a - b, 6)
    return deltas


def compute_impact_score(deltas: dict[str, float]) -> float:
    """Compute overall impact magnitude from deltas via RMS + sigmoid."""
    if not deltas:
        return 0.0
    squared = [d * d for d in deltas.values()]
    rms = (sum(squared) / len(squared)) ** 0.5
    return round(1.0 / (1.0 + 2.718 ** (-5.0 * rms)), 4)


# source: ADR-0095
# source: ADR-0095
_MINIMAL_IMPACT_THRESHOLD = 0.1
_NEGLIGIBLE_DELTA_MAGNITUDE = 0.01
_CRITICAL_IMPACT_THRESHOLD = 0.5
_MEANINGFUL_IMPACT_THRESHOLD = 0.3


def generate_interpretation(
    mechanism: str,
    deltas: dict[str, float],
    impact_score: float,
) -> str:
    """Generate human-readable interpretation of ablation results."""
    if impact_score < _MINIMAL_IMPACT_THRESHOLD:
        return f"Ablation of {mechanism} had minimal impact on system behavior."

    sorted_deltas = sorted(deltas.items(), key=lambda x: abs(x[1]), reverse=True)
    top_effects = sorted_deltas[:3]

    parts = [f"Ablation of {mechanism} (impact={impact_score:.2f}):"]
    for metric, delta in top_effects:
        direction = "increased" if delta > 0 else "decreased"
        magnitude = abs(delta)
        if magnitude > _NEGLIGIBLE_DELTA_MAGNITUDE:
            parts.append(f"  {metric} {direction} by {magnitude:.4f}")

    if impact_score > _CRITICAL_IMPACT_THRESHOLD:
        parts.append("  This mechanism appears CRITICAL for system function.")
    elif impact_score > _MEANINGFUL_IMPACT_THRESHOLD:
        parts.append("  This mechanism contributes meaningfully to system behavior.")
    else:
        parts.append("  This mechanism has a minor but measurable contribution.")

    return "\n".join(parts)


def create_ablation_result(
    mechanism: str,
    baseline: dict[str, float],
    ablation: dict[str, float],
) -> AblationResult:
    """Create a complete ablation result from baseline and ablation metrics."""
    deltas = compute_ablation_deltas(baseline, ablation)
    impact = compute_impact_score(deltas)
    interp = generate_interpretation(mechanism, deltas, impact)

    return AblationResult(
        mechanism=mechanism,
        baseline_metrics=baseline,
        ablation_metrics=ablation,
        deltas=deltas,
        impact_score=impact,
        interpretation=interp,
    )


# -- Neutral values (identity functions for disabled mechanisms) ---------------


def neutral_encoding_strength() -> float:
    """Return neutral encoding strength (no oscillatory modulation)."""
    return 1.0


def neutral_retrieval_strength() -> float:
    """Return neutral retrieval strength (no oscillatory modulation)."""
    return 1.0


def neutral_ltp_modulation() -> float:
    """Return neutral LTP modulation (no astrocyte/neuromodulation)."""
    return 1.0


def neutral_schema_match() -> float:
    """Return neutral schema match (no schema acceleration)."""
    return 0.0


def neutral_interference_score() -> float:
    """Return neutral interference (no interference management)."""
    return 0.0


def neutral_separation_index() -> float:
    """Return neutral separation (no pattern separation)."""
    return 0.0


def neutral_hippocampal_dependency() -> float:
    """Return neutral dependency (no two-stage model)."""
    return 0.5


def neutral_scaling_factor() -> float:
    """Return neutral scaling (no homeostatic plasticity)."""
    return 1.0
