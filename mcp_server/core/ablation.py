"""Ablation framework -- lesion study simulator for Cortex mechanisms.

In neuroscience, ablation studies remove or disable brain regions to measure
their contribution. This module applies the same methodology to Cortex:
disable individual neuroscience mechanisms and measure the impact on
system-level behavior.

Each mechanism has an enable/disable flag. When disabled:
- The mechanism returns neutral/identity values (no modulation)
- Other mechanisms continue operating normally
- System-level metrics are tracked for comparison

Pure business logic -- no I/O (the env-var read is a single os.environ
lookup, performed only when an E1 verification campaign sets it; in
production the var is never set so the lookup is a constant-time miss).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum


def is_mechanism_disabled(mechanism: "Mechanism | str") -> bool:
    """True iff CORTEX_ABLATE_<NAME>=1 is set for this mechanism.

    Production hot-paths call this at the entry point and short-circuit to
    a no-op when True. Used by the E1 verification campaign
    (benchmarks/lib/ablation_runner.py) to produce per-mechanism causal
    deltas; in production the env var is never set so every check is a
    single dict lookup.

    Reads os.environ on every call -- callers are not in a tight loop;
    test env varies per-run; production env never changes mid-process.
    DO NOT memoize.

    Accepts either a Mechanism enum (uses .name -> e.g. "OSCILLATORY_CLOCK")
    or a string (upper-cased, hyphens normalized).
    """
    if isinstance(mechanism, Mechanism):
        name = mechanism.name
    else:
        name = str(mechanism).upper().replace("-", "_")
    return os.environ.get(f"CORTEX_ABLATE_{name}") == "1"


class Mechanism(Enum):
    """Enumeration of the ablatable units (the neuroscience-grounded
    mechanisms plus retrieval/maintenance flags; some mechanisms expose more
    than one ablation flag). CONFABULATION_GATE (C1 source/reality-monitoring
    read-side enforcement — gates the consolidation-time confabulation check
    that flags an episodic->semantic promotion whose combined source evidence is
    INFERRED with zero perceptual grounding, plus the per-hit recall
    confabulation_risk annotation; disabled makes both a no-op, so a promotion is
    annotated exactly as it was pre-C1-read-side and recall hits carry no risk
    flag — with no change to recall ordering/membership either way).
    ATTENTIONAL_CONTROL (A1 central-executive read-side — a soft attentional
    re-weight over the FULL recall candidate set:
    recall_pipeline.attentional_focus_rerank runs the same allocate_attention
    pass A1 already provides, using the recall query as the top-down cue plus
    bottom-up salience, and applies a small multiplicative nudge
    ``score·(1 + weight·(attn − 1/n))`` to each candidate; uniform/no-signal
    attention gives a per-candidate factor of exactly 1.0 so recall ordering is
    unchanged, and the candidate set is NEVER truncated to the Cowan working-set
    ceiling; disabled returns the candidate list untouched) is the most recent
    addition."""

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

    Data only — mutmut skips the body of any `@dataclass`-decorated class
    (`mutmut/mutation/file_mutation.py:236`; issue #262 3rd pass, #282).
    `ablation_config_is_enabled/disable/enable/disable_all_except` below
    carry the logic as free functions instead.
    """

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
    config: "AblationConfig",  # noqa: ARG001 — config: uniform call shape, see docstring
    *mechanisms: Mechanism,
) -> "AblationConfig":
    """Disable all mechanisms except the specified ones.

    ``config`` is unread — kept for a uniform ``(config, ...)`` call shape;
    the result always replaces ``disabled`` wholesale (matches the
    pre-extraction method's own behavior of ignoring prior state).
    """
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


# source: pre-existing tuned values, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
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
