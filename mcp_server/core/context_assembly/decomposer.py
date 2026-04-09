"""Priority-budgeted structured prompt assembly.

**The core primitive**: a prompt template is a set of typed placeholders,
each with a priority rank, each optionally paired with a domain-aware
condenser. When the filled template would exceed the context window,
placeholders are progressively condensed — lowest priority first —
until the total fits. If any placeholder was materially reduced, a
truncation warning banner is injected at the top so the LLM knows
what it's missing.

**The invention is Clément Deust's** (original Swift implementation in
ai-architect-prd-builder/packages/AIPRDMetaPromptingEngine/Sources/
Pipeline/ContextDecomposer.swift). This Python port adapts the semantics
1:1 for Cortex. No paper precedent was found for:
  1) priority-driven progressive condensation with per-type condensers, or
  2) injecting explicit truncation awareness into the prompt.

The closest neighbors in the literature are Anthropic's Contextual
Retrieval (chunk-level LLM summaries, different goal) and various
token-budgeting recipes in LangChain-style libraries (flat truncation,
no priorities, no domain awareness, no model-side warning).
"""
from __future__ import annotations

from typing import Callable

from mcp_server.core.context_assembly.budget import (
    AssemblyMetrics,
    Placeholder,
    available_budget,
    estimate_tokens,
    truncate_to_budget,
)
from mcp_server.core.context_assembly.warning import build_truncation_banner


# ── Main entry point ────────────────────────────────────────────────────


def assemble_prompt(
    template: str,
    placeholders: list[Placeholder],
    *,
    context_window: int,
    headroom: float = 0.75,
    estimator: Callable[[str], int] = estimate_tokens,
    safety_margin_tokens: int = 64,
) -> tuple[str, AssemblyMetrics]:
    """Fill a template with priority-budgeted placeholders.

    Algorithm (ported from Swift ContextDecomposer.assemblePrompt):

    1. Compute the template shell tokens (template with all placeholders
       substituted with empty strings).
    2. variable_budget = available_budget - shell_tokens.
    3. If total placeholder content fits within variable_budget, use
       all originals verbatim.
    4. Otherwise, progressive proportional condensation: sort placeholders
       by descending priority number (least important first). For each,
       assign either its full content (if it fits a proportional share)
       or the condenser-reduced version.
    5. Post-assembly safety loop: while the final prompt exceeds
       (context_window - safety_margin_tokens), iteratively halve the
       lowest-importance (highest priority number) placeholder. Stop
       when no further reduction is possible.
    6. Build a truncation warning banner listing all placeholders whose
       surviving fraction is below 90%. Prepend to the prompt.

    Args:
        template: the raw template string containing placeholder keys.
        placeholders: list of Placeholder objects.
        context_window: total tokens the target model accepts.
        headroom: fraction of the window reserved for input. Default 0.75
            (leaves 25% for the response).
        estimator: token counting function. Default uses the conservative
            char/3 heuristic; swap for tiktoken at the integration site.
        safety_margin_tokens: extra tokens kept free at the very end.

    Returns:
        (final_prompt, metrics) where metrics records original vs final
        token counts per placeholder.
    """
    budget = available_budget(context_window, headroom)

    # Step 1: compute shell (template with empty placeholders)
    shell = template
    for p in placeholders:
        shell = shell.replace(p.key, "")
    shell_tokens = estimator(shell)

    variable_budget = max(300, budget - shell_tokens)

    # Track metrics
    metrics = AssemblyMetrics(
        total_shell_tokens=shell_tokens,
        total_variable_budget=variable_budget,
    )
    for p in placeholders:
        metrics.original_tokens[p.key] = estimator(p.value)

    # Step 2: total variable tokens
    total_variable = sum(metrics.original_tokens.values())

    # Step 3: fast path — everything fits
    effective: dict[str, str] = {}
    if total_variable <= variable_budget:
        for p in placeholders:
            effective[p.key] = p.value
    else:
        # Step 4: progressive condensation
        # Sort by priority DESC (high priority number → least important → condensed first)
        sorted_ph = sorted(placeholders, key=lambda p: p.priority, reverse=True)

        remaining = variable_budget
        assigned: dict[str, str] = {}

        for i, p in enumerate(sorted_ph):
            orig = metrics.original_tokens[p.key]
            # Proportional share of remaining budget among not-yet-assigned
            not_yet = len(sorted_ph) - i
            share = max(50, remaining // max(1, not_yet))

            if orig <= share:
                # Fits — use full content
                assigned[p.key] = p.value
                remaining -= orig
            else:
                # Over share — apply condenser if available, else truncate
                if p.condenser is not None:
                    reduced = p.condenser(p.value, share)
                else:
                    reduced = truncate_to_budget(p.value, share, estimator)
                assigned[p.key] = reduced
                remaining -= min(estimator(reduced), remaining)

        effective = assigned

    # Record post-condensation token counts
    for p in placeholders:
        metrics.final_tokens[p.key] = estimator(effective.get(p.key, p.value))

    # Assemble prompt
    prompt = template
    for p in placeholders:
        prompt = prompt.replace(p.key, effective.get(p.key, p.value))

    # Step 5: post-assembly safety loop
    # If still over budget, halve the least-important placeholder
    # iteratively until under limit or nothing left to trim.
    sorted_desc = sorted(placeholders, key=lambda p: p.priority, reverse=True)
    current_values = dict(effective)
    max_iterations = 50
    iteration = 0

    while (
        estimator(prompt) > (context_window - safety_margin_tokens)
        and iteration < max_iterations
    ):
        did_trim = False
        for p in sorted_desc:
            val = current_values.get(p.key, p.value)
            if estimator(val) <= 50:
                continue  # Can't meaningfully halve further
            # Halve at the nearest line boundary in the first half
            half_idx = len(val) // 2
            prefix = val[:half_idx]
            last_newline = prefix.rfind("\n")
            if last_newline > 0:
                halved = val[: last_newline + 1]
            else:
                halved = prefix
            current_values[p.key] = halved
            # Rebuild prompt
            prompt = template
            for pp in placeholders:
                prompt = prompt.replace(
                    pp.key, current_values.get(pp.key, pp.value)
                )
            did_trim = True
            break
        if not did_trim:
            break
        iteration += 1

    # Update final metrics after the safety loop
    for p in placeholders:
        metrics.final_tokens[p.key] = estimator(
            current_values.get(p.key, p.value)
        )
    metrics.total_final_tokens = estimator(prompt)

    # Step 6: truncation warning banner
    banner = build_truncation_banner(metrics)
    if banner:
        prompt = banner + "\n\n" + prompt

    return prompt, metrics
