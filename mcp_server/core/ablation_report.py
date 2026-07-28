"""Ablation study reporting and batch planning.

Formats ablation results into neuroscience-style reports and plans
full ablation studies across all mechanisms.

Pure business logic -- no I/O.
"""

from __future__ import annotations

from mcp_server.core.ablation import AblationResult, Mechanism


def plan_full_ablation_study(
    exclude: set[str] | None = None,
) -> list[str]:
    """Plan a full ablation study: one experiment per mechanism.

    Args:
        exclude: Mechanism names to skip (e.g., core infrastructure).

    Returns:
        List of mechanism names to ablate, in recommended order
        (most downstream first, then upstream).
    """
    exclude = exclude or set()
    order = [
        Mechanism.ATTENTIONAL_CONTROL,
        Mechanism.CONFABULATION_GATE,
        Mechanism.ENTITY_DEDUP,
        Mechanism.FORWARD_MODEL,
        Mechanism.GOAL_MAINTENANCE,
        Mechanism.STRESS_MODULATION,
        Mechanism.EXTINCTION,
        Mechanism.TARGETED_REACTIVATION,
        Mechanism.SLEEP_PHASES,
        Mechanism.CONFLICT_MONITOR,
        Mechanism.DUAL_PROCESS,
        Mechanism.MOOD_CONGRUENT_RERANK,
        Mechanism.VALUE_PRIORITY,
        Mechanism.EMOTIONAL_RETRIEVAL,
        Mechanism.EMOTIONAL_DECAY,
        Mechanism.SURPRISE_MOMENTUM,
        Mechanism.CO_ACTIVATION,
        Mechanism.ADAPTIVE_DECAY,
        Mechanism.SPREADING_ACTIVATION,
        Mechanism.HDC,
        Mechanism.HOPFIELD,
        Mechanism.DENDRITIC_CLUSTERS,
        Mechanism.SYNAPTIC_TAGGING,
        Mechanism.EMOTIONAL_TAGGING,
        Mechanism.MICROGLIAL_PRUNING,
        Mechanism.ACTIVE_FORGETTING,
        Mechanism.COMPRESSION,
        Mechanism.RECONSOLIDATION,
        Mechanism.PATTERN_SEPARATION,
        Mechanism.INTERFERENCE,
        Mechanism.SCHEMA_ENGINE,
        Mechanism.TRIPARTITE_SYNAPSE,
        Mechanism.HOMEOSTATIC_PLASTICITY,
        Mechanism.SYNAPTIC_PLASTICITY,
        Mechanism.ENGRAM_ALLOCATION,
        Mechanism.TWO_STAGE_MODEL,
        Mechanism.NEUROMODULATION,
        Mechanism.HABITUATION,
        Mechanism.PREDICTIVE_CODING,
        Mechanism.CASCADE,
        Mechanism.OSCILLATORY_CLOCK,
    ]
    return [m.value for m in order if m.value not in exclude]


def _format_result_section(result: AblationResult) -> list[str]:
    """Format a single ablation result as report lines."""
    return [
        f"### {result.mechanism} (impact: {result.impact_score:.2f})",
        result.interpretation,
        "",
    ]


# source: pre-existing tuned values, extracted unchanged (#197 family 3);
# provenance not recorded at introduction. Mirror the interpretation
# thresholds in mcp_server.core.ablation.generate_interpretation.
_CRITICAL_IMPACT_THRESHOLD = 0.5
_IMPORTANT_IMPACT_THRESHOLD = 0.3


def _format_summary_section(results: list[AblationResult]) -> list[str]:
    """Format the summary section of the ablation report."""
    sorted_results = sorted(results, key=lambda r: r.impact_score, reverse=True)
    critical = [
        r for r in sorted_results if r.impact_score > _CRITICAL_IMPACT_THRESHOLD
    ]
    important = [
        r
        for r in sorted_results
        if _IMPORTANT_IMPACT_THRESHOLD < r.impact_score <= _CRITICAL_IMPACT_THRESHOLD
    ]
    minor = [r for r in sorted_results if r.impact_score <= _IMPORTANT_IMPACT_THRESHOLD]

    return [
        "## Summary",
        f"- **Critical mechanisms** ({len(critical)}): "
        f"{', '.join(r.mechanism for r in critical)}",
        f"- **Important mechanisms** ({len(important)}): "
        f"{', '.join(r.mechanism for r in important)}",
        f"- **Minor mechanisms** ({len(minor)}): "
        f"{', '.join(r.mechanism for r in minor)}",
    ]


def format_ablation_report(results: list[AblationResult]) -> str:
    """Format all ablation results into a report.

    Styled like a neuroscience methods and results section.
    """
    lines = [
        "# Ablation Study Report",
        "",
        "## Methods",
        f"We systematically ablated {len(results)} mechanisms and measured",
        "the impact on system-level memory metrics.",
        "",
        "## Results (sorted by impact)",
        "",
    ]

    sorted_results = sorted(results, key=lambda r: r.impact_score, reverse=True)
    for r in sorted_results:
        lines.extend(_format_result_section(r))

    lines.extend(_format_summary_section(results))

    return "\n".join(lines)
