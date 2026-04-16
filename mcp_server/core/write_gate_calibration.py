"""Write-gate threshold auto-calibration.

Per Taleb antifragile audit AF-5: the write-gate threshold should respond
to observed traffic. If too many submissions pass (90%+ acceptance), the
gate is too loose — most "novel" attempts aren't actually novel and we
are storing noise. If too few pass (<10%), the gate is too tight and we
lose real signal.

Target acceptance rate: 50% (Jaynes-style maximum entropy — half of
novel attempts pass, which maximises the information content of the
accept/reject signal, E.T. Jaynes, *Probability Theory: The Logic of
Science*, 2003, Ch. 11). This is the most informative operating point:
the gate is maximally discriminative when acceptance is balanced.

Control mechanism: the calibrator holds an exponential moving average
(EMA) of the accept signal over the last ~N gate decisions, and nudges
the threshold by a fixed step when |acceptance - target| exceeds a
tolerance band. EMA decay 0.95 means ~20-sample memory; step 0.02 gives
convergence in ~50 corrections at the worst case, which is fast enough
to respond to regime changes but slow enough to not oscillate.

Pure business logic — no I/O. The state lives in-process; persistence
is optional and gated on the A3 schema migration landing.

References:
    Jaynes, E. T. (2003). *Probability Theory: The Logic of Science*.
        Cambridge University Press. Ch. 11 — the principle of maximum
        entropy implies 50% acceptance maximises information per decision.
    Taleb, N. N. (2012). *Antifragile: Things That Gain from Disorder*.
        Random House. — systems that calibrate from their own rejection
        signal are antifragile to distribution shift.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ── Control constants (source: operational defaults, see module docstring) ──

TARGET_ACCEPTANCE_RATE: float = 0.5  # Jaynes max-entropy operating point.
EMA_DECAY: float = 0.95  # ~20-sample effective memory window.
ADJUSTMENT_STEP: float = 0.02  # Bounded per-update threshold delta.
TOLERANCE_BAND: float = 0.15  # |observed - target| below this -> no adjustment.
MIN_THRESHOLD: float = 0.05  # Floor — below this, almost everything stores.
MAX_THRESHOLD: float = 0.95  # Ceiling — above this, almost nothing stores.
MIN_SAMPLES_BEFORE_ADJUST: int = 20  # Avoid adjusting on noise.


@dataclass
class CalibrationState:
    """Per-domain write-gate calibration state.

    Invariants:
      - 0.0 <= acceptance_ema <= 1.0
      - MIN_THRESHOLD <= threshold <= MAX_THRESHOLD
      - total_observations >= 0
    """

    domain: str = ""
    threshold: float = 0.4  # Default matches WRITE_GATE_THRESHOLD seed.
    acceptance_ema: float = 0.5  # Seed at target; diverges with data.
    total_observations: int = 0
    last_adjustment_at: int = 0  # Observation count when threshold last moved.


# ── EMA update ────────────────────────────────────────────────────────────


def update_acceptance_ema(
    current_ema: float,
    accepted: bool,
    decay: float = EMA_DECAY,
) -> float:
    """Update the accept-rate EMA after one gate decision.

    Contract:
      pre:  0.0 <= current_ema <= 1.0; 0 < decay < 1.
      post: returned value in [0, 1]; EMA moves toward 1.0 if accepted
            else toward 0.0 at rate (1 - decay).

    The update rule is the standard one-sided exponential moving average:
        EMA' = decay * EMA + (1 - decay) * observation
    with observation = 1 if accepted else 0.
    """
    observation = 1.0 if accepted else 0.0
    new_ema = decay * current_ema + (1.0 - decay) * observation
    # Clamp — floating-point drift, not a real invariant violation.
    return max(0.0, min(1.0, new_ema))


# ── Threshold adjustment ──────────────────────────────────────────────────


def compute_threshold_adjustment(
    current_threshold: float,
    acceptance_ema: float,
    *,
    target: float = TARGET_ACCEPTANCE_RATE,
    step: float = ADJUSTMENT_STEP,
    tolerance: float = TOLERANCE_BAND,
    min_threshold: float = MIN_THRESHOLD,
    max_threshold: float = MAX_THRESHOLD,
) -> float:
    """Return the new threshold given the current EMA.

    Contract:
      pre:  0 <= acceptance_ema <= 1; min <= current_threshold <= max.
      post: returned threshold is in [min, max].
            If |acceptance_ema - target| <= tolerance, threshold unchanged.
            If acceptance_ema > target + tolerance (too permissive), raise
                threshold by `step` (clamped to max).
            If acceptance_ema < target - tolerance (too tight), lower
                threshold by `step` (clamped to min).

    The direction rule: high acceptance means gate is too permissive ->
    raise threshold. Low acceptance means gate is too strict -> lower
    threshold. Sign is fixed by the gate predicate ``novelty >= threshold``
    (see ``predictive_coding_gate.gate_decision``).
    """
    delta = acceptance_ema - target
    if abs(delta) <= tolerance:
        return current_threshold
    direction = step if delta > 0 else -step
    new_threshold = current_threshold + direction
    return max(min_threshold, min(max_threshold, new_threshold))


# ── State lifecycle ────────────────────────────────────────────────────────


def observe_gate_decision(
    state: CalibrationState,
    accepted: bool,
    *,
    min_samples: int = MIN_SAMPLES_BEFORE_ADJUST,
) -> CalibrationState:
    """Record one gate decision and (possibly) adjust the threshold.

    Contract:
      pre:  state is a valid CalibrationState.
      post: returned state has total_observations = prev + 1, EMA updated
            via ``update_acceptance_ema``, and threshold adjusted IFF
            total_observations >= min_samples AND |EMA - target| >
            tolerance. When adjusted, last_adjustment_at is set to the
            new total_observations.

    The ``min_samples`` guard prevents adjusting on cold-start noise:
    with EMA decay 0.95 and seed EMA=0.5, the first ~20 observations
    carry most of the initial-condition bias.
    """
    new_ema = update_acceptance_ema(state.acceptance_ema, accepted)
    new_total = state.total_observations + 1

    if new_total < min_samples:
        return CalibrationState(
            domain=state.domain,
            threshold=state.threshold,
            acceptance_ema=new_ema,
            total_observations=new_total,
            last_adjustment_at=state.last_adjustment_at,
        )

    new_threshold = compute_threshold_adjustment(state.threshold, new_ema)
    new_last_adj = (
        new_total if new_threshold != state.threshold else state.last_adjustment_at
    )
    return CalibrationState(
        domain=state.domain,
        threshold=new_threshold,
        acceptance_ema=new_ema,
        total_observations=new_total,
        last_adjustment_at=new_last_adj,
    )


# ── Registry (per-process, per-domain) ─────────────────────────────────────

_STATES: dict[str, CalibrationState] = {}


def get_state(domain: str, default_threshold: float = 0.4) -> CalibrationState:
    """Fetch or lazily-initialise the calibration state for a domain.

    Pure-ish: the module-level dict is process-local state; safe because
    calibration is monotonically tolerant of restarts (seed back to the
    default threshold -> converges again in ~50 observations).
    """
    key = domain or ""
    if key not in _STATES:
        _STATES[key] = CalibrationState(
            domain=key,
            threshold=default_threshold,
        )
    return _STATES[key]


def record(
    domain: str,
    accepted: bool,
    *,
    default_threshold: float = 0.4,
) -> CalibrationState:
    """Convenience: observe a decision and store the updated state."""
    state = get_state(domain, default_threshold=default_threshold)
    new_state = observe_gate_decision(state, accepted)
    _STATES[domain or ""] = new_state
    return new_state


def reset_all_states() -> None:
    """Test hook: clear the in-process calibration registry."""
    _STATES.clear()


def effective_threshold(
    domain: str,
    default_threshold: float = 0.4,
) -> float:
    """Return the calibration-adjusted threshold for a domain.

    Falls back to ``default_threshold`` when no calibration state exists
    (cold start — first write ever for this domain).
    """
    state = _STATES.get(domain or "")
    if state is None:
        return default_threshold
    return state.threshold
