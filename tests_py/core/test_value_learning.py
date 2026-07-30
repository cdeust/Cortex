"""Tests for core.value_learning (B2 RL value + credit assignment).

Verifies the TD value update (Schultz RPE / Sutton & Barto), eligibility-trace
credit assignment, the value->priority mappings, and — critically — that the
reward mapping stays identical to the existing DA-RPE so the value layer and the
dopamine signal never disagree on what "reward" means.
"""

from __future__ import annotations

import math

from mcp_server.core.value_learning import (
    TRACE_LAMBDA,
    VALUE_ALPHA,
    VALUE_PRIOR,
    ValueUpdate,
    assign_credit,
    outcome_to_reward,
    retention_bonus,
    retrieval_priority,
    td_update,
    value_update_as_dict,
)


# ── Reward mapping parity with DA-RPE (shared source of truth) ──────────────
def test_reward_mapping_matches_da_rpe():
    """value_learning.outcome_to_reward must equal the reward mapping baked into
    neuromodulation_channels.compute_dopamine_rpe, else the two RL signals would
    disagree on what a 'reward' is."""
    from mcp_server.core.neuromodulation_channels import compute_dopamine_rpe

    for pos, neg in [(True, False), (False, True), (False, False)]:
        for imp in (0.0, 0.3, 0.5, 1.0):
            reward = outcome_to_reward(pos, neg, imp)
            # Recover the DA-RPE's 'actual' by setting baseline such that
            # delta is observable: da = 1 + (actual - baseline). With
            # baseline=0, da-1 == actual (before clamping). Use a low baseline
            # and importance to keep within the unclamped region.
            da, _ = compute_dopamine_rpe(pos, neg, imp, da_baseline=0.0)
            # da = clamp(1 + (actual - 0)) = clamp(1 + actual); actual in [0.1,1]
            recovered_actual = da - 1.0
            assert math.isclose(reward, recovered_actual, abs_tol=1e-9), (
                pos,
                neg,
                imp,
                reward,
                recovered_actual,
            )


def test_outcome_to_reward_values():
    assert math.isclose(outcome_to_reward(True, False, 0.5), 0.85)
    assert math.isclose(outcome_to_reward(False, True, 0.5), 0.15)
    assert outcome_to_reward(False, False, 0.5) == 0.5


# ── TD update (Schultz / Sutton & Barto) ────────────────────────────────────
def test_td_update_moves_toward_reward():
    new_v, delta = td_update(0.5, 1.0)
    assert delta == 0.5
    assert math.isclose(new_v, 0.5 + VALUE_ALPHA * 0.5)  # 0.55


def test_td_update_negative_reward_decreases():
    new_v, delta = td_update(0.8, 0.15)
    assert delta < 0
    assert new_v < 0.8


def test_td_update_clamped():
    new_v, _ = td_update(0.99, 1.0, alpha=1.0)
    assert new_v <= 1.0
    new_v2, _ = td_update(0.01, 0.0, alpha=1.0)
    assert new_v2 >= 0.0


def test_td_update_eligibility_scales_step():
    full, _ = td_update(0.5, 1.0, eligibility=1.0)
    half, _ = td_update(0.5, 1.0, eligibility=0.5)
    assert (full - 0.5) > (half - 0.5) > 0


# ── Credit assignment with eligibility traces ───────────────────────────────
def _mem(mid, value=None, importance=0.5):
    d = {"id": mid, "importance": importance}
    if value is not None:
        d["value"] = value
    return d


def test_credit_top_hit_gets_most():
    recalled = [_mem(1), _mem(2), _mem(3)]
    updates = assign_credit(recalled, outcome_positive=True, outcome_negative=False)
    assert len(updates) == 3
    # Eligibility decays with rank.
    assert updates[0].eligibility == 1.0
    assert math.isclose(updates[1].eligibility, TRACE_LAMBDA)
    assert math.isclose(updates[2].eligibility, TRACE_LAMBDA**2)
    # Top hit's value moves the most on a positive outcome.
    gains = [u.new_value - u.old_value for u in updates]
    assert gains[0] > gains[1] > gains[2] > 0


def test_credit_positive_raises_negative_lowers():
    recalled = [_mem(1, value=0.5)]
    up = assign_credit(recalled, True, False)[0]
    down = assign_credit(recalled, False, True)[0]
    assert up.new_value > 0.5
    assert down.new_value < 0.5


def test_credit_neutral_regresses_toward_prior():
    high = [_mem(1, value=0.9)]
    low = [_mem(1, value=0.1)]
    up_high = assign_credit(high, False, False)[0]
    up_low = assign_credit(low, False, False)[0]
    # Neutral reward 0.5 pulls both toward the prior.
    assert up_high.new_value < 0.9
    assert up_low.new_value > 0.1


def test_credit_uses_prior_when_value_absent():
    up = assign_credit([_mem(1)], True, False)[0]
    assert up.old_value == VALUE_PRIOR


def test_credit_skips_entries_without_id():
    recalled = [{"importance": 0.5}, _mem(2)]
    updates = assign_credit(recalled, True, False)
    assert len(updates) == 1
    assert updates[0].memory_id == 2


def test_credit_importance_scales_positive_reward():
    hi = assign_credit([_mem(1, value=0.5, importance=1.0)], True, False)[0]
    lo = assign_credit([_mem(1, value=0.5, importance=0.0)], True, False)[0]
    # Higher importance -> higher positive reward -> larger value gain.
    assert hi.new_value > lo.new_value


# ── Value -> priority mappings ──────────────────────────────────────────────
def test_retention_bonus_monotone():
    assert retention_bonus(0.5) == 1.0  # neutral: no effect
    assert retention_bonus(1.0) > retention_bonus(0.75) > 1.0
    assert retention_bonus(0.0) == 1.0  # low value never accelerates decay


def test_retrieval_priority_boost_and_penalty():
    base = 2.0
    boosted = retrieval_priority(base, 1.0)
    penalized = retrieval_priority(base, 0.0)
    neutral = retrieval_priority(base, VALUE_PRIOR)
    assert boosted > base
    assert penalized < base
    assert math.isclose(neutral, base)


def test_value_update_as_dict_roundtrip():
    # Every float carries a 5th decimal digit and is not integer-valued —
    # this is deliberate: round(x, 4) vs round(x, 5) and round(x, 4) vs
    # round(x) (ndigits=None, which returns an int) must all be
    # OBSERVABLY different for this test to be a real assertion rather
    # than one that happens to pass regardless of the rounding precision
    # (issue #282 mutation-testing gap: 0.5/0.55/1.0/0.1 round identically
    # at 4 vs 5 digits and int-truncate to values that still compare equal
    # via Python's int==float coercion).
    u = ValueUpdate(
        memory_id=7,
        old_value=0.512345,
        new_value=0.556789,
        delta=0.512345,
        eligibility=0.812345,
        effective_alpha=0.198765,
    )
    d = value_update_as_dict(u)
    assert d["memory_id"] == 7
    assert d["new_value"] == round(0.556789, 4)
    assert d["old_value"] == round(0.512345, 4)
    assert d["delta"] == round(0.512345, 4)
    assert d["eligibility"] == round(0.812345, 4)
    assert d["effective_alpha"] == round(0.198765, 4)
