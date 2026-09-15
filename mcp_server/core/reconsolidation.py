"""Memory reconsolidation — memories become labile on retrieval and may be rewritten.

source: ADR-0236"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from mcp_server.core.ablation import Mechanism, is_mechanism_disabled
from mcp_server.core.extinction import (
    deprecate as _deprecate,
    spontaneous_recovery as _recover,
    reinstate as _reinstate,
)


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


def _posix_dirname(path: str) -> str:
    """Pure-string equivalent of ``posixpath.dirname`` (core may not import
    os; issue #560). ``memory_directory``/``current_directory`` are
    project-relative posix-style strings, never raw OS paths.

    source: issue #560"""
    sep_index = path.rfind("/") + 1
    head = path[:sep_index]
    if head and head != "/" * len(head):
        head = head.rstrip("/")
    return head


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
    elif _posix_dirname(memory_directory) == _posix_dirname(current_directory):
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


@dataclass
class ReconsolidationResult:
    """Result of reconsolidation decision with emotional modulation.

    source: ADR-0236
    """

    action: Literal["none", "update", "archive"]
    prediction_error: float = 0.0
    strength_delta: float = 0.0
    emotional_multiplier: float = 1.0


# source: ADR-0236

# source: ADR-0236
_HIGH_PLASTICITY_THRESHOLD: float = 0.5


def decide_action(
    mismatch: float,
    stability: float = 0.0,
    plasticity: float = 1.0,
    is_protected: bool = False,
    emotional_arousal: float = 0.0,
    age_days: float = 0.0,
    *,
    low_threshold: float = 0.15,  # source: ADR-0236
    high_threshold: float = 0.65,  # source: ADR-0236
) -> ReconsolidationResult:
    """Determine reconsolidation action based on mismatch and memory state.

    source: ADR-0236

    Returns ReconsolidationResult with action, prediction_error,
    strength_delta, and emotional_multiplier.
    """

    if is_mechanism_disabled(Mechanism.RECONSOLIDATION):
        # No-op: never reconsolidate; memory left unchanged.
        return ReconsolidationResult(action="none")
    if is_protected:
        return ReconsolidationResult(action="none")

    # source: ADR-0236

    prediction_error = mismatch * (1.0 - stability * 0.5)

    # source: ADR-0236

    age_factor = min(age_days / 30.0, 1.0) * 0.15
    effective_low = low_threshold + age_factor + (stability * 0.2)
    effective_high = high_threshold + (stability * 0.1)

    # Recently accessed (high plasticity) memories are MORE susceptible
    if plasticity > _HIGH_PLASTICITY_THRESHOLD:
        effective_low -= 0.1
        effective_high -= 0.1

    if prediction_error < effective_low:
        return ReconsolidationResult(action="none", prediction_error=prediction_error)
    if prediction_error >= effective_high:
        return ReconsolidationResult(
            action="archive",
            prediction_error=prediction_error,
            strength_delta=-0.2,
        )

    # source: ADR-0236

    emotional_multiplier = 1.0 + min(emotional_arousal, 0.8)
    strength_delta = prediction_error * 0.1 * emotional_multiplier

    return ReconsolidationResult(
        action="update",
        prediction_error=prediction_error,
        strength_delta=strength_delta,
        emotional_multiplier=emotional_multiplier,
    )


# source: ADR-0236
# source: ADR-0236
_MERGE_KEEP_CHARS: int = 500


def merge_content(old_content: str, new_context: str, max_length: int = 2000) -> str:
    """Merge new context into existing memory content.

    If merged exceeds max_length, keeps first 500 + last 500 of old + full new.
    """
    merged = f"{old_content}\n--- Updated context ---\n{new_context}"
    if len(merged) <= max_length:
        return merged

    old_prefix = old_content[:_MERGE_KEEP_CHARS]
    old_suffix = (
        old_content[-_MERGE_KEEP_CHARS:] if len(old_content) > _MERGE_KEEP_CHARS else ""
    )
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


# source: ADR-0236

# source: ADR-0236
_NON_USEFUL_ACCESS_THRESHOLD: int = 5


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
    if access_count > _NON_USEFUL_ACCESS_THRESHOLD:
        return max(current_stability - increment * 0.5, 0.0)
    return current_stability


# source: ADR-0236


@dataclass
class ReconsolidationOutcome:
    """Result of evaluating one retrieved candidate for reconsolidation.

    source: ADR-0236"""

    action: Literal["none", "update", "archive"]
    heat_delta: float = 0.0
    valence_delta: float = 0.0
    update_last_accessed: bool = False
    mismatch: float = 0.0
    prediction_error: float = 0.0
    # source: ADR-0236

    extinction_strength: float | None = None


# source: ADR-0236

# source: ADR-0236
_RECONS_HEAT_BUMP_UPDATE: float = 0.05
_RECONS_HEAT_BUMP_NONE: float = 0.02  # successful passive retrieval
_RECONS_HEAT_BUMP_ARCHIVE: float = -0.10
_RECONS_VALENCE_STEP: float = 0.10  # |Δvalence| per "update" with non-neutral query
_RECONS_QUERY_VALENCE_FLOOR: float = 0.10  # below this, query is treated as neutral


def compute_reconsolidation_action(
    memory: dict,
    query: str,
    *,
    embedding_similarity: float | None = None,
    current_directory: str = "",
    context_tokens: set[str] | None = None,
    query_valence: float = 0.0,
) -> ReconsolidationOutcome:
    """Decide what to do to a memory given the current retrieval context.

    Pure: takes the memory dict (as produced by recall) + query context,
    returns a ReconsolidationOutcome the caller applies via the store.
    Composes `compute_mismatch` + `decide_action` and translates the
    abstract action into concrete heat / valence / timestamp deltas.

    Preconditions: memory is a non-None dict containing at least
    ``memory_id``; query is a string (may be empty).
    Postconditions: returns a ReconsolidationOutcome whose action is one of
    {"none", "update", "archive"}; heat_delta is bounded to
    [-0.10, +0.05]; valence_delta is bounded to [-0.10, +0.10].

    source: ADR-0236"""
    if memory is None:
        return ReconsolidationOutcome(action="none")

    tags_raw = memory.get("tags") or []
    if isinstance(tags_raw, str):
        memory_tags: set[str] = {tags_raw}
    else:
        memory_tags = {str(t) for t in tags_raw}

    ctx_tokens = context_tokens if context_tokens is not None else set()

    mismatch = compute_mismatch(
        embedding_similarity=embedding_similarity,
        memory_directory=memory.get("directory", "") or "",
        current_directory=current_directory or "",
        memory_last_accessed=memory.get("last_accessed"),
        memory_tags=memory_tags,
        context_tokens=ctx_tokens,
    )

    decision = decide_action(
        mismatch,
        stability=float(memory.get("stability", 0.0) or 0.0),
        plasticity=float(memory.get("plasticity", 1.0) or 1.0),
        is_protected=bool(memory.get("is_protected", False)),
        emotional_arousal=abs(float(memory.get("emotional_valence", 0.0) or 0.0)),
        age_days=float(memory.get("age_days", 0.0) or 0.0),
    )

    if decision.action == "archive":
        return ReconsolidationOutcome(
            action="archive",
            heat_delta=_RECONS_HEAT_BUMP_ARCHIVE,
            valence_delta=0.0,
            update_last_accessed=True,
            mismatch=mismatch,
            prediction_error=decision.prediction_error,
        )

    if decision.action == "update":
        # source: ADR-0236

        heat_delta = _RECONS_HEAT_BUMP_UPDATE * decision.emotional_multiplier
        # Cap the bump at the same magnitude as the bound documented in
        # ReconsolidationOutcome's contract — the emotional multiplier can
        # push us above _RECONS_HEAT_BUMP_UPDATE alone.
        heat_delta = min(heat_delta, _RECONS_HEAT_BUMP_UPDATE * 2.0)
        valence_delta = 0.0
        if abs(query_valence) >= _RECONS_QUERY_VALENCE_FLOOR:
            # source: ADR-0236

            sign = 1.0 if query_valence > 0 else -1.0
            valence_delta = sign * _RECONS_VALENCE_STEP
        return ReconsolidationOutcome(
            action="update",
            heat_delta=heat_delta,
            valence_delta=valence_delta,
            update_last_accessed=True,
            mismatch=mismatch,
            prediction_error=decision.prediction_error,
        )

    # source: ADR-0236

    return ReconsolidationOutcome(
        action="none",
        heat_delta=_RECONS_HEAT_BUMP_NONE,
        valence_delta=0.0,
        update_last_accessed=True,
        mismatch=mismatch,
        prediction_error=decision.prediction_error,
    )


# source: ADR-0236


def compute_extinction_action(
    memory: dict,
    *,
    operation: Literal["deprecate", "recover", "reinstate"] = "deprecate",
    trials: int = 1,
    hours_elapsed: float = 0.0,
) -> ReconsolidationOutcome:
    """Compute a reversible extinction update for a memory (E2).

    source: ADR-0236

      - ``operation="deprecate"`` grows the inhibitory tag by ``trials``
        unreinforced extinction trials (the reversible counterpart to
        active_forgetting's delete).
      - ``operation="recover"`` decays the tag over ``hours_elapsed``
        (spontaneous recovery — the association returns on its own).
      - ``operation="reinstate"`` clears the tag in one step (the original
        association is restored in full).

    source: ADR-0236

    Preconditions: ``memory`` is a dict (may be empty); ``trials >= 0``;
    ``hours_elapsed >= 0``.
    Postconditions: returns a ReconsolidationOutcome with ``action == "none"``
    (extinction never re-stores content) and ``update_last_accessed == False``
    (a deprecation is not a retrieval); ``extinction_strength`` is the new tag
    in [0, 1], or None when ablated.
    """

    if memory is None:
        return ReconsolidationOutcome(action="none")

    current = float(memory.get("extinction_strength", 0.0) or 0.0)
    base_heat = float(memory.get("heat", memory.get("heat_base", 0.0)) or 0.0)

    ablated = is_mechanism_disabled(Mechanism.EXTINCTION)

    if operation == "deprecate":
        out = _deprecate(base_heat, current, trials=trials)
        # source: ADR-0236

        new_tag = None if out.operation == "noop" else out.new_extinction_strength
        return ReconsolidationOutcome(
            action="none",
            extinction_strength=new_tag,
        )

    if ablated:
        # recover / reinstate are no-ops under ablation too.
        return ReconsolidationOutcome(action="none", extinction_strength=None)

    if operation == "recover":
        new_tag = _recover(current, hours_elapsed)
    elif operation == "reinstate":
        new_tag = _reinstate(current)
    else:  # pragma: no cover - guarded by Literal typing
        return ReconsolidationOutcome(action="none", extinction_strength=None)

    return ReconsolidationOutcome(action="none", extinction_strength=new_tag)
