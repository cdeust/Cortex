"""Truncation warning banner.

When the prompt decomposer must condense placeholders to fit the
context window, it injects a warning banner at the top of the final
prompt. The LLM sees an explicit list of what was cut and by how much,
so it can reason about missing information rather than hallucinating.

This is a direct port of the Swift `buildTruncationWarning` helper in
ContextDecomposer.swift. The mechanism is Clément Deust's invention —
no paper precedent has been found for injecting truncation awareness
into the prompt itself.

Original: ai-architect-prd-builder/packages/AIPRDMetaPromptingEngine/
          Sources/Pipeline/ContextDecomposer.swift → buildTruncationWarning
"""

from __future__ import annotations

from mcp_server.core.context_assembly.budget import AssemblyMetrics


# Reduction threshold below which a placeholder is considered "truncated"
# for the purposes of the warning. Matches the Swift default of 10%.
_SIGNIFICANT_REDUCTION = 0.9


def build_truncation_banner(
    metrics: AssemblyMetrics,
    reduction_threshold: float = _SIGNIFICANT_REDUCTION,
) -> str:
    """Build a ⚠️ banner listing placeholders that were materially condensed.

    Returns an empty string when no placeholder was reduced below the
    threshold (i.e. the prompt fits without loss).

    Args:
        metrics: the AssemblyMetrics populated during prompt assembly.
        reduction_threshold: a placeholder is flagged when its surviving
            fraction is below this value. Default 0.9 (10% reduction).
    """
    truncated: list[tuple[str, int, int]] = []
    for key, original in metrics.original_tokens.items():
        if original <= 0:
            continue
        final = metrics.final_tokens.get(key, 0)
        if final < original and (final / original) < reduction_threshold:
            truncated.append((key, original, final))

    if not truncated:
        return ""

    lines = [
        "⚠️ CONTEXT TRUNCATION WARNING",
        "The following sections were truncated to fit the context window.",
        "You may be missing information. Prioritize the content you CAN see.",
        "",
    ]
    for key, original, final in truncated:
        pct = int(100 * final / original) if original else 0
        lines.append(f"- {key}: {pct}% retained ({final}/{original} tokens)")
    return "\n".join(lines)
