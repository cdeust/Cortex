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

    def reduction_fraction(self, key: str) -> float:
        """Fraction of a placeholder's content that survived (0.0..1.0)."""
        orig = self.original_tokens.get(key, 0)
        if orig == 0:
            return 1.0
        fin = self.final_tokens.get(key, 0)
        return fin / orig

    def was_truncated(self, key: str, threshold: float = 0.9) -> bool:
        """True if the placeholder's surviving fraction is below threshold."""
        return self.reduction_fraction(key) < threshold


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
