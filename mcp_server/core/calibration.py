"""Calibration scoring over resolved predictions.

A prediction carries the confidence its author held when writing it. Once an
outcome is observed, that confidence can be scored by the mean squared
distance between the two.

The scale here is the single-probability one, mean((p - o)^2), which is what
scikit-learn's `brier_score_loss` and most contemporary writing call the
Brier score. Brier's own 1950 paper (*Verification of forecasts expressed in
terms of probability*, Monthly Weather Review 78(1)) sums over both
categories of a binary event and therefore reports exactly twice this
number. The ranking of forecasters is identical either way; only the
constants differ, and every reference point below is stated on the scale
this module computes.

Two reference points make a Brier score readable. A forecaster who always
says 0.5 scores exactly 0.25, whatever happens; anyone above that number is
carrying less information than a coin. A forecaster who is always right and
always certain scores 0.

The reliability breakdown says something the mean cannot: within each
confidence band, how often the prediction actually held. A well-calibrated
author's band around 0.7 is confirmed about seventy percent of the time.

Pure: no I/O, no store, no clock.

source: ADR-1076"""

from __future__ import annotations

from typing import Any, Iterable

# The score a constant 0.5 forecast earns on this scale, whatever happens,
# which is what an author who never commits is worth: mean((0.5 - o)^2) =
# 0.25 for any sequence of outcomes in {0, 1}.
# source: arithmetic, pinned by
# test_always_saying_half_scores_the_uninformative_reference
UNINFORMATIVE_BRIER = 0.25

# Reliability bands. Ten would be finer, but a band needs resolved
# predictions in it to say anything, and this store fills slowly.
# source: the decision recorded as ADR number 1076
BAND_EDGES: tuple[float, ...] = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)

SCORED_VERDICTS: dict[str, float] = {"confirmed": 1.0, "refuted": 0.0}


def outcome_of(verdict: str) -> float | None:
    """1.0 for a confirmed prediction, 0.0 for a refuted one, else None.

    An abandoned prediction has no outcome: its test was never run, so it
    says nothing about the author's calibration and is counted apart.
    """
    return SCORED_VERDICTS.get(verdict)


def brier_score(pairs: Iterable[tuple[float, float]]) -> float | None:
    """Mean squared error between stated confidence and observed outcome.

    ``pairs`` is (confidence, outcome) with outcome in {0.0, 1.0}. Returns
    None for an empty input: a score over nothing is not zero, it is absent.
    """
    squares = [(confidence - outcome) ** 2 for confidence, outcome in pairs]
    if not squares:
        return None
    return sum(squares) / len(squares)


def _band_of(confidence: float) -> tuple[float, float]:
    """The band a confidence falls in, upper edge inclusive at the top.

    Raises ValueError outside [0, 1] rather than folding the value into an
    edge band: a confidence is a probability, both table CHECK constraints
    refuse anything else, and a silent bucket would make the reliability
    diagram lie about what it measured.
    """
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence outside [0, 1]: {confidence}")
    for low, high in zip(BAND_EDGES[:-1], BAND_EDGES[1:], strict=True):
        if confidence < high:
            return (low, high)
    # Only a confidence of exactly 1.0 reaches here: the top band holds it.
    return (BAND_EDGES[-2], BAND_EDGES[-1])


def reliability(pairs: Iterable[tuple[float, float]]) -> list[dict[str, Any]]:
    """Per-band observed frequency against stated confidence, low band first.

    Only bands holding at least one resolved prediction are returned.
    """
    buckets: dict[tuple[float, float], list[tuple[float, float]]] = {}
    for confidence, outcome in pairs:
        buckets.setdefault(_band_of(confidence), []).append((confidence, outcome))
    rows: list[dict[str, Any]] = []
    for band in sorted(buckets):
        held = buckets[band]
        rows.append(
            {
                "band": [band[0], band[1]],
                "resolved": len(held),
                "mean_confidence": sum(c for c, _ in held) / len(held),
                "observed_frequency": sum(o for _, o in held) / len(held),
            }
        )
    return rows


def calibration_report(resolved: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Score a set of resolved predictions.

    Each row carries ``confidence`` and ``verdict``. Rows whose verdict has
    no outcome are counted in ``abandoned`` and scored nowhere. The report
    states ``uninformative_brier`` beside the score so the number can be
    read without knowing the literature.
    """
    pairs: list[tuple[float, float]] = []
    abandoned = 0
    for row in resolved:
        outcome = outcome_of(str(row.get("verdict", "")))
        if outcome is None:
            abandoned += 1
            continue
        pairs.append((float(row.get("confidence", 0.0)), outcome))
    return {
        "scored": len(pairs),
        "abandoned": abandoned,
        "brier": brier_score(pairs),
        "uninformative_brier": UNINFORMATIVE_BRIER,
        "confirmed": sum(1 for _, outcome in pairs if outcome == 1.0),
        "refuted": sum(1 for _, outcome in pairs if outcome == 0.0),
        "reliability": reliability(pairs),
    }
