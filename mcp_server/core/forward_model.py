"""Cerebellar forward model (B3) — one-step-ahead prediction with error-driven
correction of the estimate.

The cerebellum learns *forward models*: given the current state and an efferent
copy of the motor command, it predicts the command's sensory consequence, and
the discrepancy between that prediction and the actual afferent signal — the
sensory prediction error — drives an online correction of the model. This is
the Smith-predictor / internal-model view of cerebellar function: predict the
next state, observe it, correct the estimate by the residual.

Cortex already contains a great deal of *perceptual* prediction — the
Fristonian hierarchical predictive-coding stack
(``predictive_coding_signals``, ``hierarchical_predictive_coding``) predicts a
new item's content features from the statistics of recent memories and emits a
novelty score; ``schema_engine.compute_prediction_error`` scores schema-entity
mismatch; Titans (``titans_memory``) accumulates a surprise-momentum gradient.
What none of those do is the specific cerebellar loop this module adds: take a
*trajectory* of a scalar signal, predict the *next* value one step ahead from
the running estimate, and — crucially — **correct that estimate from the
residual error** with a fixed gain, the way a forward model is tuned by its own
prediction error. The genuinely-new primitive here is that error-driven
correction of a self-maintained estimate (a state estimator), not the act of
predicting-from-recent-statistics, which overlaps
``predictive_coding_signals.compute_sensory_prediction``.

Neuroscience basis (DOIs verified against Crossref):
  - Wolpert, Miall & Kawato (1998), "Internal models in the cerebellum,"
    Trends in Cognitive Sciences 2:338-347
    (doi:10.1016/S1364-6613(98)01221-2). The cerebellum acquires forward
    internal models that predict the sensory consequences of actions; the
    sensory prediction error is the teaching signal that tunes the model.
  - Ito (2008), "Control of mental activities by internal models in the
    cerebellum," Nature Reviews Neuroscience 9:304-313 (doi:10.1038/nrn2332).
    The same forward-model / error-correction machinery generalises from motor
    control to the prediction of non-motor (mental) state trajectories.

Honesty note (zetetic standard, matching source_monitoring.py /
attentional_control.py). This is a **minimal, deterministic forward-model
primitive** and is flagged LOW AI PRIORITY in the neuroscience-gap analysis
(docs/provenance/neuroscience-gap-feasibility.md, B3: "Forward/inverse models
are standard in control/model-based RL, but the mapping to a text-memory
system is weak"). Concretely, what it IS:

  - a one-dimensional error-correcting estimator: the prediction is the running
    estimate, the correction is a fixed-gain (alpha) EMA step toward the
    observed value, and the emitted signal is the one-step residual error. This
    is the scalar Smith-predictor skeleton, nothing more.

and what it is NOT:

  - NOT a learned cerebellar circuit. ``CORRECTION_GAIN`` is a fixed
    engineering constant, not a plasticity rule fitted against a
    task-performance signal; there are no climbing-fibre error channels,
    Purkinje cells, or eligibility traces.
  - NOT a multivariate or nonlinear dynamics model — it tracks a single scalar
    with a linear EMA. Feeding it a feature vector reduces the vector to one
    scalar (mean activation) first.
  - NOT the perceptual novelty scorer. The *prediction-from-recent-statistics*
    step overlaps ``compute_sensory_prediction``; the only genuinely-distinct
    contribution is the online estimate correction and the one-step residual it
    exposes as a corrective error signal.

Pure business logic -- no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── Constants ───────────────────────────────────────────────────────────────
# Fixed correction gain (alpha) of the estimate-update EMA: the fraction of the
# residual error folded back into the estimate at each step. 0 = frozen model
# (never corrects), 1 = the estimate jumps to the last observation (no memory).
# 0.5 balances the two. A fixed engineering constant — NOT a learned plasticity
# rate (see the honesty note).
CORRECTION_GAIN = 0.5

# Residual magnitudes at or below this are treated as "predicted correctly" —
# the model made no meaningful error, so downstream contributions are identity.
# Keeps small numeric jitter from registering as a correction signal.
ERROR_DEADBAND = 0.05


@dataclass
class ForwardModelState:
    """State of a running scalar forward model.

    ``estimate``   — the current one-step-ahead prediction (updated by
                     corrections; this is what ``predict`` returns).
    ``error``      — the last signed residual (observed - predicted).
    ``corrected``  — the estimate *after* folding in the last correction.
    ``n_updates``  — how many observations have corrected the model.
    """

    estimate: float
    error: float = 0.0
    corrected: float = 0.0
    n_updates: int = 0


def forward_model_state_as_dict(state: "ForwardModelState") -> dict:
    """A free function, not a method: mutmut categorically excludes the
    body of any `@dataclass`-decorated class (`mutmut/mutation/
    file_mutation.py:236`), so logic placed on `ForwardModelState` methods
    would carry zero mutation coverage no matter how the test loader names
    the module (issue #262 3rd pass; issue #282).
    """
    return {
        "estimate": round(state.estimate, 6),
        "error": round(state.error, 6),
        "corrected": round(state.corrected, 6),
        "n_updates": state.n_updates,
    }


# ── The two primitive operations ────────────────────────────────────────────
def predict(state: ForwardModelState) -> float:
    """One-step-ahead prediction: the forward model's current estimate.

    The model predicts that the next observation will equal its running
    estimate. This is the forward-model output an efferent copy would query
    before the actual sensory feedback arrives.
    """
    return state.estimate


def correction(
    predicted: float,
    actual: float,
    *,
    gain: float = CORRECTION_GAIN,
    deadband: float = ERROR_DEADBAND,
) -> tuple[float, float]:
    """Correct a prediction from the observed value; return (error, corrected).

    ``error`` is the signed residual ``actual - predicted`` — the sensory
    prediction error that, in the cerebellum, is the teaching signal. The
    corrected estimate is a fixed-gain step from ``predicted`` toward ``actual``
    (``predicted + gain * error``). Residuals whose magnitude is within
    ``deadband`` are treated as a correct prediction: the error is reported but
    the estimate is left unchanged (no spurious correction from numeric jitter).
    """
    error = actual - predicted
    if abs(error) <= deadband:
        return error, predicted
    g = max(0.0, min(1.0, gain))
    return error, predicted + g * error


# ── Running the model over a trajectory ─────────────────────────────────────
def run_forward_model(
    trajectory: list[float],
    *,
    gain: float = CORRECTION_GAIN,
    deadband: float = ERROR_DEADBAND,
) -> ForwardModelState:
    """Replay predict→observe→correct across a scalar ``trajectory``.

    The estimate is seeded with the first observation (no error can be scored
    before the model has seen anything), then each subsequent value is predicted
    one step ahead and used to correct the estimate. The returned state's
    ``error`` is the residual for the *last* observation given the model built
    from all earlier ones — i.e. how surprising the most recent step was.

    An empty trajectory yields a zeroed state; a single point yields the seeded
    estimate with zero error (nothing to predict yet).
    """
    if not trajectory:
        return ForwardModelState(estimate=0.0)

    state = ForwardModelState(
        estimate=float(trajectory[0]), corrected=float(trajectory[0])
    )
    for actual in trajectory[1:]:
        pred = predict(state)
        error, corrected = correction(pred, float(actual), gain=gain, deadband=deadband)
        state.estimate = corrected
        state.error = error
        state.corrected = corrected
        state.n_updates += 1
    return state


def prediction_error(
    trajectory: list[float],
    actual: float,
    *,
    gain: float = CORRECTION_GAIN,
    deadband: float = ERROR_DEADBAND,
) -> float:
    """Signed one-step forward-model error of ``actual`` given ``trajectory``.

    Builds the forward model from ``trajectory`` (the recent history), predicts
    the next value, and returns the signed residual against the actually-
    observed ``actual``. Positive = the observation exceeded the model's
    expectation; negative = fell short; ``0.0`` when the residual is within the
    deadband (predicted correctly) or when there is no history to predict from.
    """
    if not trajectory:
        return 0.0
    state = run_forward_model(trajectory, gain=gain, deadband=deadband)
    error, _ = correction(predict(state), float(actual), gain=gain, deadband=deadband)
    return error


# ── Vector convenience (reduces a feature dict to the tracked scalar) ────────
def scalar_of(features: dict[str, float]) -> float:
    """Reduce a feature vector to the single scalar the model tracks.

    The forward model is one-dimensional (see the honesty note); a caller
    holding a feature dict (e.g. the sensory feature vector from
    ``predictive_coding_signals.extract_sensory_features``) collapses it to its
    mean activation here before feeding the model. Empty vector → 0.0.
    """
    if not features:
        return 0.0
    vals = list(features.values())
    return sum(vals) / len(vals)
