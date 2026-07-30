"""Token budgeting primitives for structured context assembly.

Provides token estimation and budget allocation utilities used by the
prompt decomposer and stage assembler.

Original Swift design by Clément Deust in ai-architect-prd-builder
(packages/AIPRDMetaPromptingEngine/Sources/Pipeline/ContextDecomposer.swift).
Python port with Cortex-specific adaptations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


# ── Token estimation ─────────────────────────────────────────────────────
# Conservative ~1 token per 3 Unicode scalars heuristic. Matches the Swift
# fallback when no provider-specific tokenizer is available. For higher
# accuracy, swap for tiktoken at the integration site.


def estimate_tokens(text: str) -> int:
    """Return a conservative token estimate (chars // 3, min 1).

    Kept simple and synchronous. Callers that need provider-accurate
    counts should pass a custom `estimator` function into the decomposer.
    """
    if not text:
        return 0
    return max(1, len(text) // 3)


# ── Budget allocation ────────────────────────────────────────────────────


def available_budget(context_window: int, headroom: float = 0.75) -> int:
    """Compute the writable token budget for a given context window.

    Leaves (1 - headroom) of the window for the response. Default 0.75
    matches the Swift ContextDecomposer.availableTokenBudget default.
    """
    if context_window <= 0:
        return 0
    return int(context_window * headroom)


# Floor on a single item's share of the remaining budget. Below this an
# item condenses to a fragment that carries no usable meaning, so the
# share rule never allocates less.
# source: Swift ContextDecomposer progressive-condensation loop
#   (ai-architect-prd-builder, ContextDecomposer.swift) — the same `max(50,
#   remaining / notYetAssigned)` rule this port has used since the
#   decomposer landed.
MIN_ITEM_SHARE_TOKENS = 50


def proportional_share(remaining: int, not_yet_assigned: int) -> int:
    """Share of ``remaining`` allocated to the next of N unassigned items.

    Even split of what is left, floored at ``MIN_ITEM_SHARE_TOKENS``. The
    floor is what lets a packing loop condense every item instead of
    dropping the ones that arrive after the budget runs out.
    """
    return max(MIN_ITEM_SHARE_TOKENS, remaining // max(1, not_yet_assigned))


# ── Placeholder types ────────────────────────────────────────────────────


@dataclass(frozen=True)
class Placeholder:
    """A typed slot in a prompt template.

    Attributes:
        key: template marker (e.g. "{{QUERY}}", "{{CONTEXT}}").
        value: content that will fill the slot.
        priority: importance rank. **Lower number = more important.**
            Higher numbers get condensed first when over budget. This
            matches the Swift semantics where `priority: 1` is highest.
        condenser: optional domain-aware reduction function. Signature
            is `(value: str, target_tokens: int) -> str`. When None,
            generic truncation is applied.
    """

    key: str
    value: str
    priority: int = 1
    condenser: Callable[[str, int], str] | None = None


@dataclass
class AssemblyMetrics:
    """Bookkeeping for prompt assembly — what was trimmed and by how much.

    Consumed by warning.py to build the banner injected at the top of
    the final prompt so the LLM knows what was cut.
    """

    original_tokens: dict[str, int] = field(default_factory=dict)
    final_tokens: dict[str, int] = field(default_factory=dict)
    total_shell_tokens: int = 0
    total_variable_budget: int = 0
    total_final_tokens: int = 0


def assembly_metrics_reduction_fraction(metrics: "AssemblyMetrics", key: str) -> float:
    """Fraction of a placeholder's content that survived (0.0..1.0).

    A free function, not a method: mutmut categorically excludes the body
    of any `@dataclass`-decorated class (`mutmut/mutation/file_mutation.py:
    236`), so logic placed on `AssemblyMetrics` methods would carry zero
    mutation coverage no matter how the test loader names the module
    (issue #262 3rd pass; issue #282).
    """
    orig = metrics.original_tokens.get(key, 0)
    if orig == 0:
        return 1.0
    fin = metrics.final_tokens.get(key, 0)
    return fin / orig


def assembly_metrics_was_truncated(
    metrics: "AssemblyMetrics", key: str, threshold: float = 0.9
) -> bool:
    """True if the placeholder's surviving fraction is below threshold."""
    return assembly_metrics_reduction_fraction(metrics, key) < threshold


# ── Generic truncation ──────────────────────────────────────────────────


def truncate_to_budget(
    text: str,
    token_budget: int,
    estimator: Callable[[str], int] = estimate_tokens,
) -> str:
    """Truncate text to fit within a token budget, preferring line boundaries.

    Algorithm (ported from Swift truncateToTokenBudget):
      1. If already within budget, return as-is.
      2. Estimate target character count as budget * 3.
      3. Cut at the last newline before that point to preserve line structure.
      4. Fall back to hard cut if no newline exists.
    """
    if estimator(text) <= token_budget:
        return text
    target_chars = max(1, token_budget * 3)
    prefix = text[:target_chars]
    last_newline = prefix.rfind("\n")
    if last_newline > 0:
        return prefix[: last_newline + 1]
    return prefix
