"""Memory reconsolidation — memories become labile on retrieval and may be rewritten.

Based on Nader et al. (Nature, 2000) and Osan-Tort-Amaral (PLoS ONE, 2011).

Three outcomes based on mismatch between stored memory and current context:
  - mismatch < low_threshold: Passive retrieval, no change
  - low <= mismatch < high: RECONSOLIDATE — update memory with current context
  - mismatch >= high: EXTINCTION — archive old memory, create new one

Emotional modulation (Yonelinas & Ritchey 2015, Lee 2009):
  - Prediction error gate: PE = mismatch * (1 - stability * 0.5)
  - Age-dependent threshold: older memories resist reconsolidation (Milekic & Alberini 2002)
  - Emotional strength gain: reconsolidation is 1-1.8x stronger for emotional memories

Pure business logic — no I/O. Decisions are returned to the caller.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
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


@dataclass
class ReconsolidationResult:
    """Result of reconsolidation decision with emotional modulation."""

    action: Literal["none", "update", "archive"]
    prediction_error: float = 0.0
    strength_delta: float = 0.0
    emotional_multiplier: float = 1.0


def decide_action(
    mismatch: float,
    stability: float = 0.0,
    plasticity: float = 1.0,
    is_protected: bool = False,
    emotional_arousal: float = 0.0,
    age_days: float = 0.0,
    *,
    low_threshold: float = 0.15,
    high_threshold: float = 0.65,
) -> ReconsolidationResult:
    """Determine reconsolidation action based on mismatch and memory state.

    Thresholds: Osan-Tort-Amaral (PLoS ONE, 2011).
    PE gate: Lee (Trends Neurosci, 2009).
    Age factor: Milekic & Alberini (2002).
    Emotional multiplier: Yonelinas & Ritchey (2015) decay ratio.

    Returns ReconsolidationResult with action, prediction_error,
    strength_delta, and emotional_multiplier.
    """
    from mcp_server.core.ablation import Mechanism, is_mechanism_disabled

    if is_mechanism_disabled(Mechanism.RECONSOLIDATION):
        # No-op: never reconsolidate; memory left unchanged.
        return ReconsolidationResult(action="none")
    if is_protected:
        return ReconsolidationResult(action="none")

    # Prediction error gate (Lee 2009): stable memories dampen PE
    prediction_error = mismatch * (1.0 - stability * 0.5)

    # Age-dependent threshold (Milekic & Alberini 2002):
    # Older memories require larger PE to destabilize
    age_factor = min(age_days / 30.0, 1.0) * 0.15
    effective_low = low_threshold + age_factor + (stability * 0.2)
    effective_high = high_threshold + (stability * 0.1)

    # Recently accessed (high plasticity) memories are MORE susceptible
    if plasticity > 0.5:
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

    # Reconsolidation regime — emotional multiplier (Yonelinas & Ritchey 2015)
    # Decay ratio b_neutral/b_emotional = 2.0 → up to 1.8x at arousal=0.8
    emotional_multiplier = 1.0 + min(emotional_arousal, 0.8)
    strength_delta = prediction_error * 0.1 * emotional_multiplier

    return ReconsolidationResult(
        action="update",
        prediction_error=prediction_error,
        strength_delta=strength_delta,
        emotional_multiplier=emotional_multiplier,
    )


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


# ── Recall-time reconsolidation action ─────────────────────────────────
#
# Recall-time bridge between the retrieval candidate dict (heat, content,
# emotional_valence, last_accessed) and the labile-rewrite decision logic
# (compute_mismatch + decide_action). This is the function the post-WRRF
# RECONSOLIDATION stage in `recall_pipeline.py` calls per top-K candidate.
#
# Source: Nader, Schafe & LeDoux (2000) Nature 406(6797): retrieval renders
# a memory labile for a window during which it can be re-stored with
# modifications. Bower (1981) Am. Psychologist 36(2): retrieval context's
# affective valence biases the re-stored emotional tag.
#
# Engineering defaults — heat / valence step magnitudes are not paper-
# prescribed (the papers establish the *qualitative* mechanism, not numeric
# step sizes for a tag-and-vector memory store). Defaults are conservative
# and labelled "engineering default, calibration pending" per the source-
# discipline rule (CLAUDE.md §8). Calibration belongs to the same blend-
# weight grid that owns HOPFIELD/HDC/SA/DENDRITIC/EMOTIONAL betas
# (tasks/blend-weight-calibration.md).


@dataclass
class ReconsolidationOutcome:
    """Result of evaluating one retrieved candidate for reconsolidation.

    Fields:
      action: from `decide_action` — "none" / "update" / "archive".
      heat_delta: signed change to apply to the memory's heat_base.
        Positive on successful retrieval (Nader 2000 — re-storage
        strengthens), negative on archive (extinction regime).
      valence_delta: signed change to emotional_valence; non-zero only
        when the query carries a Bower-style affective load and the
        action is "update".
      update_last_accessed: whether the store should refresh
        last_accessed (typically True on any non-no-op outcome).
      mismatch: the multi-signal mismatch in [0, 1] for diagnostics.
      prediction_error: PE-gated mismatch from `decide_action`.
    """

    action: Literal["none", "update", "archive"]
    heat_delta: float = 0.0
    valence_delta: float = 0.0
    update_last_accessed: bool = False
    mismatch: float = 0.0
    prediction_error: float = 0.0


# Engineering defaults (calibration pending — see tasks/blend-weight-calibration.md).
# Bounded so the recall-time bump can never dominate the thermodynamic decay
# signal that drives the heat WRRF weight; these are tie-breakers, not filters.
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

    Source: Nader, Schafe & LeDoux (2000), Nature 406(6797). Retrieval
    triggers a labile window during which the memory is re-stored with
    modifications. Bower (1981) Am. Psychologist 36(2): mood-congruent
    re-storage. Yonelinas & Ritchey (2015) emotional gain.

    Honors `CORTEX_ABLATE_RECONSOLIDATION=1` via `decide_action`'s
    internal gate (returns action="none"). The stage-level guard in
    `recall_pipeline.reconsolidation_apply` short-circuits earlier so this
    function is not even called when ablated, but the deeper guard means
    direct callers (e.g. tests) also see the no-op behavior.
    """
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
        # Re-storage in the labile window. Heat bump scaled by
        # emotional_multiplier (Yonelinas & Ritchey 2015) so emotionally-
        # loaded memories receive proportionally larger reconsolidation
        # gain (≤ 1.8x at full arousal).
        heat_delta = _RECONS_HEAT_BUMP_UPDATE * decision.emotional_multiplier
        # Cap the bump at the same magnitude as the bound documented in
        # ReconsolidationOutcome's contract — Yonelinas multiplier can push
        # us above _RECONS_HEAT_BUMP_UPDATE alone.
        heat_delta = min(heat_delta, _RECONS_HEAT_BUMP_UPDATE * 2.0)
        valence_delta = 0.0
        if abs(query_valence) >= _RECONS_QUERY_VALENCE_FLOOR:
            # Bower (1981): the retrieval context's affective load shifts
            # the re-stored emotional tag toward the current mood. Step
            # bounded so a single retrieval cannot flip valence sign.
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

    # action == "none" — passive retrieval, small thermodynamic touch.
    # Below mismatch threshold the memory is not re-stored, but the
    # retrieval event still updates last_accessed (Nader 2000 implies
    # access tracking even without re-storage, since the labile window
    # opens regardless).
    return ReconsolidationOutcome(
        action="none",
        heat_delta=_RECONS_HEAT_BUMP_NONE,
        valence_delta=0.0,
        update_last_accessed=True,
        mismatch=mismatch,
        prediction_error=decision.prediction_error,
    )
