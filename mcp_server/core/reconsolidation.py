"""Memory reconsolidation — memories become labile on retrieval and may be rewritten.

Based on Nader et al. (Nature, 2000) and Osan-Tort-Amaral (PLoS ONE, 2011).

Three outcomes based on mismatch between stored memory and current context:
  - mismatch < low_threshold: Passive retrieval, no change
  - low <= mismatch < high: RECONSOLIDATE — update memory with current context
  - mismatch >= high: EXTINCTION — archive old memory, create new one

Pure business logic — no I/O. Decisions are returned to the caller.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Literal


def _temporal_distance(memory_last_accessed: str | None) -> float:
    """Compute normalized temporal distance (0-1) since last access."""
    if not memory_last_accessed:
        return 0.5
    try:
        last = datetime.fromisoformat(memory_last_accessed)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        hours = (datetime.now(timezone.utc) - last).total_seconds() / 3600.0
        return min(hours / 168.0, 1.0)  # normalize to 1 week
    except (ValueError, TypeError):
        return 0.5


def _tag_divergence(memory_tags: set[str], context_tokens: set[str]) -> float:
    """Compute tag divergence via Jaccard distance."""
    if memory_tags and context_tokens:
        intersection = len(memory_tags & context_tokens)
        union = len(memory_tags | context_tokens)
        return 1.0 - (intersection / union if union > 0 else 0.0)
    if not memory_tags and not context_tokens:
        return 0.0
    return 1.0


def compute_mismatch(
    *,
    embedding_similarity: float | None,
    memory_directory: str,
    current_directory: str,
    memory_last_accessed: str | None,
    memory_tags: set[str],
    context_tokens: set[str],
) -> float:
    """Compute multi-signal mismatch between stored memory and retrieval context.

    Signals (weighted):
      1. Embedding distance (0.5): 1.0 - cosine_similarity
      2. Directory distance (0.2): 0.0/0.5/1.0
      3. Temporal distance (0.15): hours since last access, normalized to 1 week
      4. Tag divergence (0.15): 1.0 - jaccard_similarity
    """
    emb_distance = 0.5 if embedding_similarity is None else 1.0 - embedding_similarity

    if memory_directory == current_directory:
        dir_distance = 0.0
    elif os.path.dirname(memory_directory) == os.path.dirname(current_directory):
        dir_distance = 0.5
    else:
        dir_distance = 1.0

    mismatch = (
        0.5 * emb_distance
        + 0.2 * dir_distance
        + 0.15 * _temporal_distance(memory_last_accessed)
        + 0.15 * _tag_divergence(memory_tags, context_tokens)
    )
    return max(0.0, min(1.0, mismatch))


def decide_action(
    mismatch: float,
    stability: float = 0.0,
    plasticity: float = 1.0,
    is_protected: bool = False,
    *,
    low_threshold: float = 0.3,
    high_threshold: float = 0.7,
) -> Literal["none", "update", "archive"]:
    """Determine reconsolidation action based on mismatch and memory state.

    Returns:
      "none" — no modification (stable or low mismatch)
      "update" — merge new context into existing memory
      "archive" — archive old memory, create new one
    """
    if is_protected:
        return "none"

    # Stable memories need more mismatch to trigger reconsolidation
    effective_low = low_threshold + (stability * 0.2)
    effective_high = high_threshold + (stability * 0.1)

    # Recently accessed (high plasticity) memories are MORE susceptible
    if plasticity > 0.5:
        effective_low -= 0.1
        effective_high -= 0.1

    if mismatch < effective_low:
        return "none"
    if mismatch < effective_high:
        return "update"
    return "archive"


def merge_content(old_content: str, new_context: str, max_length: int = 2000) -> str:
    """Merge new context into existing memory content.

    If merged exceeds max_length, keeps first 500 + last 500 of old + full new.
    """
    merged = f"{old_content}\n--- Updated context ---\n{new_context}"
    if len(merged) <= max_length:
        return merged

    old_prefix = old_content[:500]
    old_suffix = old_content[-500:] if len(old_content) > 500 else ""
    if old_suffix:
        return (
            f"{old_prefix}\n...\n{old_suffix}\n--- Updated context ---\n{new_context}"
        )
    return f"{old_prefix}\n--- Updated context ---\n{new_context}"


def compute_plasticity_decay(
    current_plasticity: float,
    hours_elapsed: float,
    half_life_hours: float = 6.0,
    spike: float = 0.3,
) -> float:
    """Spike plasticity on access with exponential decay since last update.

    Plasticity decays with half-life, then spikes on each access.
    """
    if hours_elapsed > 0 and half_life_hours > 0:
        current_plasticity *= 2 ** (-hours_elapsed / half_life_hours)
    return min(current_plasticity + spike, 1.0)


def update_stability(
    current_stability: float,
    was_useful: bool,
    access_count: int,
    increment: float = 0.1,
) -> float:
    """Update stability based on usefulness feedback.

    Useful retrievals increase stability; frequent non-useful retrievals decrease it.
    """
    if was_useful:
        return min(current_stability + increment, 1.0)
    if access_count > 5:
        return max(current_stability - increment * 0.5, 0.0)
    return current_stability
