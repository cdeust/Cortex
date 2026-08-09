"""Tests for core.near_dup_calibration (I6-D2, INC6.4)."""

from __future__ import annotations

import pytest

from mcp_server.shared.near_dup_calibration import (
    STRATA,
    THRESHOLD_CANDIDATES,
    CandidatePair,
    LabeledPair,
    build_components,
    bucket_by_stratum,
    precision_by_threshold,
    select_threshold,
    stratified_sample,
    stratum_for,
)


# ── stratum_for ──────────────────────────────────────────────────────────


def test_stratum_for_boundaries():
    assert stratum_for(0.75) == "0.75-0.80"
    assert stratum_for(0.799) == "0.75-0.80"
    assert stratum_for(0.80) == "0.80-0.85"
    assert stratum_for(0.85) == "0.85-0.90"
    assert stratum_for(0.90) == "0.90-0.95"
    assert stratum_for(0.95) == "0.95-1.00"
    assert stratum_for(1.0) == "0.95-1.00"


def test_stratum_for_below_floor_and_above_one():
    assert stratum_for(0.74999) is None
    assert stratum_for(1.001) is None


def test_strata_are_contiguous_and_exhaustive():
    # No gaps between consecutive stratum boundaries.
    for i in range(len(STRATA) - 1):
        assert STRATA[i][1] == STRATA[i + 1][0]


# ── bucket_by_stratum ────────────────────────────────────────────────────


def test_bucket_by_stratum_groups_correctly():
    pairs = [
        CandidatePair(1, 2, 0.76),
        CandidatePair(3, 4, 0.86),
        CandidatePair(5, 6, 0.99),
        CandidatePair(7, 8, 0.50),  # below floor, dropped
    ]
    buckets = bucket_by_stratum(pairs)
    assert buckets["0.75-0.80"] == [pairs[0]]
    assert buckets["0.85-0.90"] == [pairs[1]]
    assert buckets["0.95-1.00"] == [pairs[2]]
    assert "0.50" not in "".join(buckets.keys())
    assert sum(len(v) for v in buckets.values()) == 3


# ── stratified_sample ────────────────────────────────────────────────────


def test_stratified_sample_returns_all_when_under_cap():
    pairs = [CandidatePair(1, 2, 0.76), CandidatePair(3, 4, 0.77)]
    sample = stratified_sample(pairs, per_stratum=20)
    assert set(sample) == set(pairs)


def test_stratified_sample_caps_and_is_deterministic():
    pairs = [CandidatePair(i, i + 1000, 0.76) for i in range(50)]
    sample1 = stratified_sample(pairs, per_stratum=10)
    sample2 = stratified_sample(pairs, per_stratum=10)
    assert len(sample1) == 10
    assert sample1 == sample2  # deterministic, no RNG


def test_stratified_sample_spans_strata_in_order():
    pairs = [
        CandidatePair(1, 2, 0.76),
        CandidatePair(3, 4, 0.96),
    ]
    sample = stratified_sample(pairs, per_stratum=20)
    assert sample[0].similarity == 0.76
    assert sample[1].similarity == 0.96


# ── precision_by_threshold / select_threshold ───────────────────────────


def test_precision_by_threshold_perfect_at_high_band():
    labeled = [
        LabeledPair(1, 2, 0.76, verdict=False, justification="distinct topics"),
        LabeledPair(3, 4, 0.86, verdict=True, justification="same fact reworded"),
        LabeledPair(5, 6, 0.96, verdict=True, justification="byte-near-identical"),
        LabeledPair(7, 8, 0.97, verdict=True, justification="same fact"),
    ]
    stats = precision_by_threshold(labeled)
    by_threshold = {s.threshold: s for s in stats}
    assert by_threshold[0.75].precision == pytest.approx(3 / 4)
    assert by_threshold[0.95].precision == 1.0
    assert by_threshold[0.95].n_labeled == 2


def test_select_threshold_picks_lowest_qualifying():
    labeled = [
        LabeledPair(1, 2, 0.76, verdict=False, justification="x"),
        LabeledPair(3, 4, 0.81, verdict=False, justification="x"),
        LabeledPair(5, 6, 0.86, verdict=True, justification="x"),
        LabeledPair(7, 8, 0.91, verdict=True, justification="x"),
        LabeledPair(9, 10, 0.96, verdict=True, justification="x"),
    ]
    stats = precision_by_threshold(labeled)
    assert select_threshold(stats) == 0.85


def test_select_threshold_none_when_no_band_is_perfect():
    labeled = [
        LabeledPair(1, 2, 0.96, verdict=False, justification="coincidental phrasing"),
        LabeledPair(3, 4, 0.97, verdict=True, justification="same fact"),
    ]
    stats = precision_by_threshold(labeled)
    assert select_threshold(stats) is None


def test_select_threshold_lowest_threshold_wins_when_all_qualify():
    # A single labeled duplicate at 0.96 clears every threshold <= 0.96
    # (all have n_labeled=1, precision=1.0) — select_threshold must pick
    # the LOWEST qualifying candidate (0.75), not the tightest.
    labeled = [LabeledPair(1, 2, 0.96, verdict=True, justification="x")]
    stats = precision_by_threshold(labeled)
    by_threshold = {s.threshold: s for s in stats}
    assert by_threshold[0.75].n_labeled == 1
    assert by_threshold[0.75].precision == 1.0
    assert select_threshold(stats) == 0.75


def test_threshold_candidates_matches_strata_lower_bounds():
    assert THRESHOLD_CANDIDATES == tuple(low for low, _ in STRATA)


# ── build_components ─────────────────────────────────────────────────────


def test_build_components_transitive_chain():
    pairs = [
        CandidatePair(1, 2, 0.9),
        CandidatePair(2, 3, 0.9),
    ]
    components = build_components(pairs)
    assert components == [frozenset({1, 2, 3})]


def test_build_components_disjoint():
    pairs = [
        CandidatePair(1, 2, 0.9),
        CandidatePair(10, 11, 0.9),
    ]
    components = build_components(pairs)
    assert components == [frozenset({1, 2}), frozenset({10, 11})]


def test_build_components_no_pairs():
    assert build_components([]) == []


def test_build_components_sorted_by_min_member():
    pairs = [CandidatePair(50, 51, 0.9), CandidatePair(1, 2, 0.9)]
    components = build_components(pairs)
    assert components == [frozenset({1, 2}), frozenset({50, 51})]
