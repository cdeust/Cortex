"""Unit tests for A2 conflict monitoring (mcp_server/core/conflict_monitor.py).

Pure-logic tests — no store, no I/O. Cover:
  - score entropy: low for a dominant winner, high for near-ties, edge cases;
  - pairwise contradiction: same-topic opposite-polarity fires, agreement /
    disjoint topic / double-negation do not;
  - assess_conflict: high-conflict set flagged, consistent set not, empty /
    singleton neutral, loser identified as the weaker member;
  - apply_downweight: demotes and re-sorts on high conflict, no-op otherwise;
  - route_to_resolver: typed claims produce ConflictPlans, plain memories none.
"""

from __future__ import annotations

import math

import pytest

from mcp_server.core import conflict_monitor as cm


# ── score_entropy ─────────────────────────────────────────────────────────────
def test_entropy_singleton_is_zero():
    assert cm.score_entropy([0.9]) == 0.0


def test_entropy_empty_is_zero():
    assert cm.score_entropy([]) == 0.0


def test_entropy_dominant_winner_low():
    # One item far above the rest -> concentrated activation -> low entropy.
    h = cm.score_entropy([10.0, 0.1, 0.1, 0.1])
    assert 0.0 <= h < 0.4


def test_entropy_near_ties_high():
    # All equal -> uniform distribution -> normalised entropy == 1.0.
    h = cm.score_entropy([1.0, 1.0, 1.0, 1.0])
    assert h == pytest.approx(1.0, abs=1e-9)


def test_entropy_monotone_between_extremes():
    concentrated = cm.score_entropy([5.0, 0.0, 0.0])
    flat = cm.score_entropy([1.0, 0.9, 0.8])
    assert flat > concentrated


def test_entropy_handles_negative_scores():
    # FlashRank cross-encoder scores can be negative; must not raise / NaN.
    h = cm.score_entropy([-2.0, -2.1, -1.9])
    assert 0.0 <= h <= 1.0
    assert not math.isnan(h)


# ── pairwise_contradiction ────────────────────────────────────────────────────
def test_contradiction_same_topic_opposite_polarity():
    a = "the migration to postgres is complete and working"
    b = "the migration to postgres is not complete, it failed"
    assert cm.pairwise_contradiction(a, b) > 0.0


def test_contradiction_agreement_is_zero():
    a = "the build passes on ci"
    b = "the build passes reliably on ci now"
    assert cm.pairwise_contradiction(a, b) == 0.0


def test_contradiction_disjoint_topic_is_zero():
    a = "the parser handles nested json"
    b = "we never deploy on fridays"
    # No shared content tokens -> no contradiction even with a negation present.
    assert cm.pairwise_contradiction(a, b) == 0.0


def test_contradiction_empty_text_is_zero():
    assert cm.pairwise_contradiction("", "not working anything") == 0.0
    assert cm.pairwise_contradiction("something", "") == 0.0


def test_contradiction_both_negated_is_agreement():
    # Both texts carry negation about the same topic -> same polarity flag ->
    # corroboration, not contradiction (presence-based polarity; see honesty note).
    a = "the release did not ship on time"
    b = "the release was not deployed"
    assert cm.pairwise_contradiction(a, b) == 0.0


def test_contradiction_bounded_unit_interval():
    a = "cache invalidation is enabled globally"
    b = "cache invalidation is disabled globally"
    v = cm.pairwise_contradiction(a, b)
    assert 0.0 <= v <= 1.0


# ── assess_conflict ───────────────────────────────────────────────────────────
def _cand(mid, score, text, heat=0.5):
    return {"memory_id": mid, "score": score, "content": text, "heat": heat}


def test_assess_empty_is_neutral():
    a = cm.assess_conflict([])
    assert a.high is False
    assert a.conflict_score == 0.0
    assert a.competing_pair is None
    assert a.loser_id is None


def test_assess_singleton_is_neutral():
    a = cm.assess_conflict([_cand(1, 0.9, "only one memory here")])
    assert a.high is False
    assert a.conflict_score == 0.0
    assert a.competing_pair is None


def test_assess_high_conflict_near_tied_contradiction():
    cands = [
        _cand(1, 0.90, "the auth service uses jwt tokens for sessions"),
        _cand(2, 0.88, "the auth service does not use jwt tokens for sessions"),
    ]
    a = cm.assess_conflict(cands)
    assert a.high is True
    assert a.max_contradiction > 0.0
    assert a.competing_pair is not None
    assert set(a.competing_pair) == {1, 2}
    # Loser is the lower-scoring member (memory_id 2 at 0.88).
    assert a.loser_id == 2


def test_assess_consistent_set_not_high():
    cands = [
        _cand(1, 0.90, "the auth service uses jwt tokens for sessions"),
        _cand(2, 0.80, "jwt tokens are validated on every auth request"),
        _cand(3, 0.70, "sessions expire after one hour"),
    ]
    a = cm.assess_conflict(cands)
    assert a.high is False
    assert a.max_contradiction == 0.0


def test_assess_contradiction_against_dominant_winner_below_threshold():
    # A contradiction exists, but one item dominates (low entropy), so the gated
    # score stays under threshold — the disagreement is easy to resolve.
    cands = [
        _cand(1, 50.0, "the deploy pipeline is green and healthy"),
        _cand(2, 0.01, "the deploy pipeline is not green, it is broken"),
    ]
    a = cm.assess_conflict(cands)
    assert a.max_contradiction > 0.0
    assert a.entropy < 0.4
    assert a.conflict_score < cm.CONFLICT_THRESHOLD
    assert a.high is False


def test_assess_loser_tiebreak_by_heat():
    # Equal scores -> loser is the lower-heat member.
    cands = [
        _cand(1, 0.5, "feature flag rollout is enabled for all users", heat=0.9),
        _cand(2, 0.5, "feature flag rollout is not enabled for all users", heat=0.2),
    ]
    a = cm.assess_conflict(cands)
    if a.high:
        assert a.loser_id == 2


# ── apply_downweight ──────────────────────────────────────────────────────────
def test_downweight_demotes_and_resorts():
    cands = [
        _cand(1, 0.90, "the auth service uses jwt tokens for sessions"),
        _cand(2, 0.88, "the auth service does not use jwt tokens for sessions"),
    ]
    a = cm.assess_conflict(cands)
    assert a.high is True
    out = cm.apply_downweight(cands, a, penalty=0.5)
    loser = next(c for c in out if c["memory_id"] == a.loser_id)
    assert loser["score"] == pytest.approx(0.88 * 0.5)
    assert loser.get("conflict_downweighted") is True
    # Winner now strictly on top.
    assert out[0]["memory_id"] != a.loser_id


def test_downweight_noop_when_not_high():
    cands = [
        _cand(1, 0.90, "jwt tokens are validated on every auth request"),
        _cand(2, 0.80, "sessions expire after one hour"),
    ]
    a = cm.assess_conflict(cands)
    assert a.high is False
    before = [dict(c) for c in cands]
    out = cm.apply_downweight(cands, a)
    assert [c["score"] for c in out] == [c["score"] for c in before]


# ── route_to_resolver ─────────────────────────────────────────────────────────
def test_route_plain_memories_returns_empty():
    # No claim_type / entity_ids -> resolver has nothing to work with.
    cands = [
        _cand(1, 0.9, "the auth service uses jwt tokens"),
        _cand(2, 0.8, "the auth service does not use jwt tokens"),
    ]
    assert cm.route_to_resolver(cands) == []


def test_route_typed_claims_detects_conflict():
    # decision vs limitation about the same entity -> a ConflictPlan.
    cands = [
        {
            "memory_id": 10,
            "score": 0.9,
            "content": "we will use redis for the cache",
            "claim_type": "decision",
            "entity_ids": [42],
        },
        {
            "memory_id": 11,
            "score": 0.8,
            "content": "redis cannot hold the working set in memory",
            "claim_type": "limitation",
            "entity_ids": [42],
        },
    ]
    plans = cm.route_to_resolver(cands)
    assert len(plans) >= 1
    pair = plans[0]
    assert {pair.claim_a_id, pair.claim_b_id} == {10, 11}
    assert 42 in pair.overlap_entities


# ── conflict_assessment_as_dict (issue #282: dataclass mutation blindspot) ────
def test_conflict_assessment_as_dict_full_shape_and_rounding():
    assessment = cm.ConflictAssessment(
        conflict_score=0.512345,
        entropy=0.698765,
        max_contradiction=0.887654,
        competing_pair=(10, 11),
        loser_id=11,
        high=True,
    )
    d = cm.conflict_assessment_as_dict(assessment)
    assert d == {
        "conflict_score": round(0.512345, 4),
        "entropy": round(0.698765, 4),
        "max_contradiction": round(0.887654, 4),
        "competing_pair": [10, 11],
        "loser_id": 11,
        "high": True,
    }


def test_conflict_assessment_as_dict_none_competing_pair_stays_none():
    assessment = cm.ConflictAssessment(
        conflict_score=0.0,
        entropy=0.0,
        max_contradiction=0.0,
        competing_pair=None,
        loser_id=None,
        high=False,
    )
    d = cm.conflict_assessment_as_dict(assessment)
    assert d["competing_pair"] is None
    assert d["loser_id"] is None
    assert d["high"] is False
