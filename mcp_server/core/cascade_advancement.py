"""Consolidation cascade — stage advancement and reconsolidation logic.

Split from cascade.py to keep files under 300 lines.
Contains the transition logic that determines when memories advance
between consolidation stages.

Schema acceleration (Tse et al. 2007):
    Tse showed that rodents with pre-existing spatial schemas consolidated
    new schema-consistent associations in ~48 hours, compared to ~2-4 weeks
    for schema-inconsistent ones — an approximately 10-15x acceleration.
    This applies specifically to systems consolidation (LATE_LTP → CONSOLIDATED),
    not to earlier synaptic stages.

    IMPORTANT: Tse 2007 is an experimental finding, not a computational model.
    No paper in this chain (Tse 2007, van Kesteren 2012, McClelland 2013)
    provides a mathematical function mapping schema_match to consolidation
    rate. The exponential model used here (15^(-schema_match)) is an
    engineering approximation chosen to: (a) match the ~15x magnitude at
    full schema match, (b) provide diminishing returns at low match, and
    (c) equal 1.0 (no acceleration) at zero match. The functional form
    and the 15.0 constant are engineering choices, not paper-derived equations.

References:
    Kandel ER (2001) The molecular biology of memory storage.
    Tse D et al. (2007) Schemas and memory consolidation. Science 316:76-82
        (experimental: ~48h vs ~2-4 weeks for schema-consistent memories)
    Nader K et al. (2000) Fear memories require protein synthesis in the
        amygdala for reconsolidation after retrieval. Nature 406:722-726

Pure business logic — no I/O.
"""

from __future__ import annotations

from mcp_server.core.cascade_stages import (
    _STAGE_PROPERTIES,
    ConsolidationStage,
)

# ── Stage Transitions ─────────────────────────────────────────────────────


def _check_labile_advancement(
    dopamine_level: float,
    importance: float,
) -> tuple[bool, str, float]:
    """Check LABILE -> EARLY_LTP advancement conditions."""
    da_ready = dopamine_level > 1.0
    importance_ready = importance > 0.6
    readiness = min(1.0, (dopamine_level - 0.5) / 1.5 + importance * 0.3)
    if da_ready or importance_ready:
        return True, ConsolidationStage.EARLY_LTP.value, readiness
    return False, ConsolidationStage.LABILE.value, readiness


def _check_early_ltp_advancement(
    replay_count: int,
    importance: float,
) -> tuple[bool, str, float]:
    """Check EARLY_LTP -> LATE_LTP advancement conditions."""
    replay_ready = replay_count >= 1
    importance_boost = importance > 0.7
    readiness = min(1.0, replay_count / 2.0 + importance * 0.3)
    if replay_ready or importance_boost:
        return True, ConsolidationStage.LATE_LTP.value, readiness
    return False, ConsolidationStage.EARLY_LTP.value, readiness


def _check_late_ltp_advancement(
    replay_count: int,
    schema_match: float,
) -> tuple[bool, str, float]:
    """Check LATE_LTP -> CONSOLIDATED advancement conditions."""
    replay_threshold = 3 if schema_match < 0.5 else 1
    replay_ready = replay_count >= replay_threshold
    readiness = min(1.0, replay_count / max(replay_threshold, 1))
    if replay_ready:
        return True, ConsolidationStage.CONSOLIDATED.value, readiness
    return False, ConsolidationStage.LATE_LTP.value, readiness


def _check_reconsolidating_advancement(
    hours_in_stage: float,
    effective_min_dwell: float,
) -> tuple[bool, str, float]:
    """Check RECONSOLIDATING -> EARLY_LTP re-stabilization."""
    if hours_in_stage >= effective_min_dwell:
        return True, ConsolidationStage.EARLY_LTP.value, 1.0
    readiness = hours_in_stage / max(effective_min_dwell, 0.01)
    return False, ConsolidationStage.RECONSOLIDATING.value, readiness


def _effective_min_dwell(
    props: object,
    schema_match: float,
    stage: ConsolidationStage | None = None,
) -> float:
    """Compute schema-accelerated minimum dwell time.

    For systems consolidation stages (LATE_LTP, CONSOLIDATED):
        Uses exponential acceleration: dwell * 15^(-schema_match).
        At schema_match=1.0: ~15x faster (Tse 2007: ~2-4 weeks → 48h).
        At schema_match=0.0: no acceleration.
        Engineering approximation — Tse 2007 provides no equation.
        The 15.0 constant matches the experimental ~10-15x magnitude.

    For earlier stages (LABILE, EARLY_LTP, RECONSOLIDATING):
        Modest linear factor: dwell * (1 - schema_match * 0.2).
        Schema acceleration is a systems consolidation phenomenon;
        synaptic tagging stages are not schema-dependent.
    """
    if stage in (ConsolidationStage.LATE_LTP, ConsolidationStage.CONSOLIDATED):
        # Tse et al. (2007): ~15x acceleration for schema-consistent memories.
        # Engineering approximation: exponential gives diminishing returns.
        schema_factor = 15.0 ** (-schema_match)  # 1.0 at 0, ~0.067 at 1.0
    else:
        # Earlier stages: modest acceleration (hand-tuned, no paper basis)
        schema_factor = 1.0 - (schema_match * 0.2)
    return props.min_dwell_hours * schema_factor  # type: ignore[attr-defined]


def compute_advancement_readiness(
    current_stage: str,
    hours_in_stage: float,
    dopamine_level: float = 1.0,
    replay_count: int = 0,
    schema_match: float = 0.0,
    importance: float = 0.5,
) -> tuple[bool, str, float]:
    """Determine if a memory is ready to advance to the next stage.

    Returns (is_ready, next_stage_name, readiness_score_0_to_1).
    """
    try:
        stage = ConsolidationStage(current_stage)
    except ValueError:
        return False, current_stage, 0.0

    props = _STAGE_PROPERTIES[stage]
    min_dwell = _effective_min_dwell(props, schema_match, stage)

    if hours_in_stage < min_dwell:
        readiness = hours_in_stage / max(min_dwell, 0.01)
        return False, current_stage, min(readiness, 0.99)

    if stage == ConsolidationStage.LABILE:
        return _check_labile_advancement(dopamine_level, importance)
    if stage == ConsolidationStage.EARLY_LTP:
        return _check_early_ltp_advancement(replay_count, importance)
    if stage == ConsolidationStage.LATE_LTP:
        return _check_late_ltp_advancement(replay_count, schema_match)
    if stage == ConsolidationStage.RECONSOLIDATING:
        return _check_reconsolidating_advancement(hours_in_stage, min_dwell)
    return False, current_stage, 1.0


def trigger_reconsolidation(
    current_stage: str,
    mismatch_score: float,
    stability: float = 0.5,
    *,
    mismatch_threshold: float = 0.3,
) -> tuple[bool, str]:
    """Determine if retrieval should trigger reconsolidation.

    Only CONSOLIDATED and LATE_LTP memories can reconsolidate.
    Requires sufficient mismatch between retrieval context and stored context.
    Higher stability means higher mismatch threshold needed.

    Args:
        current_stage: Current consolidation stage.
        mismatch_score: Context mismatch score [0, 1].
        stability: Memory stability [0, 1]. High stability resists reconsolidation.
        mismatch_threshold: Base threshold for triggering reconsolidation.

    Returns:
        (should_reconsolidate, new_stage_name)
    """
    try:
        stage = ConsolidationStage(current_stage)
    except ValueError:
        return False, current_stage

    if stage not in (ConsolidationStage.CONSOLIDATED, ConsolidationStage.LATE_LTP):
        return False, current_stage

    effective_threshold = mismatch_threshold + stability * 0.3

    if mismatch_score >= effective_threshold:
        return True, ConsolidationStage.RECONSOLIDATING.value

    return False, current_stage
