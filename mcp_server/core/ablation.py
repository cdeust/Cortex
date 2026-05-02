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
    if hasattr(mechanism, "name"):
        name = mechanism.name
    else:
        name = str(mechanism).upper().replace("-", "_")
    return os.environ.get(f"CORTEX_ABLATE_{name}") == "1"


class Mechanism(Enum):
    """Enumeration of all ablatable Cortex mechanisms."""

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


@dataclass
class AblationConfig:
    """Configuration specifying which mechanisms are enabled/disabled."""

    disabled: set[str] = field(default_factory=set)

    def is_enabled(self, mechanism: Mechanism | str) -> bool:
        """Check if a mechanism is enabled."""
        name = mechanism.value if isinstance(mechanism, Mechanism) else mechanism
        return name not in self.disabled

    def disable(self, mechanism: Mechanism | str) -> "AblationConfig":
        """Return new config with mechanism disabled."""
        name = mechanism.value if isinstance(mechanism, Mechanism) else mechanism
        return AblationConfig(disabled=self.disabled | {name})

    def enable(self, mechanism: Mechanism | str) -> "AblationConfig":
        """Return new config with mechanism enabled."""
        name = mechanism.value if isinstance(mechanism, Mechanism) else mechanism
        return AblationConfig(disabled=self.disabled - {name})

    def disable_all_except(self, *mechanisms: Mechanism) -> "AblationConfig":
        """Disable all mechanisms except the specified ones."""
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


def generate_interpretation(
    mechanism: str,
    deltas: dict[str, float],
    impact_score: float,
) -> str:
    """Generate human-readable interpretation of ablation results."""
    if impact_score < 0.1:
        return f"Ablation of {mechanism} had minimal impact on system behavior."

    sorted_deltas = sorted(deltas.items(), key=lambda x: abs(x[1]), reverse=True)
    top_effects = sorted_deltas[:3]

    parts = [f"Ablation of {mechanism} (impact={impact_score:.2f}):"]
    for metric, delta in top_effects:
        direction = "increased" if delta > 0 else "decreased"
        magnitude = abs(delta)
        if magnitude > 0.01:
            parts.append(f"  {metric} {direction} by {magnitude:.4f}")

    if impact_score > 0.5:
        parts.append("  This mechanism appears CRITICAL for system function.")
    elif impact_score > 0.3:
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
