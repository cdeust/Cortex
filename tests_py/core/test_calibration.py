"""Calibration scoring over resolved predictions (issue #597).

source: ADR-1076
"""

from __future__ import annotations

import pytest

from mcp_server.core.calibration import (
    UNINFORMATIVE_BRIER,
    brier_score,
    calibration_report,
    outcome_of,
    reliability,
)


def test_only_a_settled_verdict_has_an_outcome() -> None:
    assert outcome_of("confirmed") == 1.0
    assert outcome_of("refuted") == 0.0
    assert outcome_of("abandoned") is None
    assert outcome_of("open") is None


def test_a_score_over_nothing_is_absent_not_zero() -> None:
    assert brier_score([]) is None


def test_certainty_that_holds_scores_zero() -> None:
    assert brier_score([(1.0, 1.0), (0.0, 0.0)]) == pytest.approx(0.0)


def test_always_saying_half_scores_the_uninformative_reference() -> None:
    pairs = [(0.5, 1.0), (0.5, 0.0), (0.5, 1.0)]

    assert brier_score(pairs) == pytest.approx(UNINFORMATIVE_BRIER)


def test_confident_and_wrong_scores_worse_than_saying_half() -> None:
    assert brier_score([(0.9, 0.0)]) > UNINFORMATIVE_BRIER


def test_reliability_reports_the_observed_frequency_per_band() -> None:
    pairs = [(0.7, 1.0), (0.65, 1.0), (0.7, 0.0), (0.1, 0.0)]

    rows = reliability(pairs)

    low, high = rows[0], rows[1]
    assert low["band"] == [0.0, 0.2]
    assert low["resolved"] == 1
    assert low["observed_frequency"] == pytest.approx(0.0)
    assert high["band"] == [0.6, 0.8]
    assert high["resolved"] == 3
    assert high["observed_frequency"] == pytest.approx(2 / 3)


def test_a_full_confidence_lands_in_the_top_band() -> None:
    rows = reliability([(1.0, 1.0)])

    assert rows[0]["band"] == [0.8, 1.0]


def test_the_report_counts_the_abandoned_apart() -> None:
    resolved = [
        {"confidence": 0.8, "verdict": "confirmed"},
        {"confidence": 0.8, "verdict": "refuted"},
        {"confidence": 0.9, "verdict": "abandoned"},
    ]

    report = calibration_report(resolved)

    assert report["scored"] == 2
    assert report["abandoned"] == 1
    assert report["confirmed"] == 1
    assert report["refuted"] == 1
    assert report["brier"] == pytest.approx(((0.8 - 1) ** 2 + (0.8 - 0) ** 2) / 2)
    assert report["uninformative_brier"] == UNINFORMATIVE_BRIER


def test_a_report_with_nothing_scored_has_no_brier() -> None:
    report = calibration_report([{"confidence": 0.5, "verdict": "abandoned"}])

    assert report["scored"] == 0
    assert report["brier"] is None
    assert report["reliability"] == []


@pytest.mark.parametrize("confidence", [-0.01, 1.01, 2.0])
def test_a_confidence_outside_zero_to_one_is_refused(confidence) -> None:
    """A silent bucket would make the reliability diagram lie (#597 review)."""
    with pytest.raises(ValueError, match="outside"):
        reliability([(confidence, 1.0)])
