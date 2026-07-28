"""Read-side integration tests for A1 attentional control.

Covers the behavior-changing wiring: the attentional focus fed into the recall
path as a soft multiplicative re-weight (recall_pipeline.attentional_focus_
rerank), mirroring the B2 value_priority / A3 goal_maintenance nudge stages.

Key invariants:
  - query-relevant / salient candidates are boosted;
  - uniform / no-signal attention is a strict identity (no reordering, scores
    unchanged within float tolerance);
  - the ablation guard disables the stage;
  - recall is NOT truncated to the Cowan FOCUS_CAPACITY ceiling — the stage is a
    soft re-weight over the FULL candidate set;
  - the stage reuses A1's pure allocate_attention (no reimplemented softmax).
"""

from __future__ import annotations

import copy
import os

from mcp_server.core import recall_pipeline as rp
from mcp_server.core.attentional_control import FOCUS_CAPACITY_DEFAULT


def _cands():
    return [
        {"memory_id": 1, "content": "grocery list for the weekend", "score": 0.60},
        {"memory_id": 2, "content": "memory decay half-life tuning", "score": 0.55},
    ]


# ── Boost: query-relevant candidate rises ───────────────────────────────────
def test_relevant_candidate_boosted_above_stronger_offtopic():
    out = rp.attentional_focus_rerank(_cands(), "memory decay half-life")
    # m2 is query-relevant → nudged above the off-topic m1 despite lower base.
    assert out[0]["memory_id"] == 2
    assert out[0]["score"] > 0.55  # boosted


def test_salient_candidate_gets_bottom_up_capture():
    # No query overlap for either, but m2 is far more salient (importance +
    # |valence|) → bottom-up salience lifts its attention weight and score.
    cands = [
        {
            "memory_id": 1,
            "content": "alpha beta",
            "score": 1.0,
            "importance": 0.0,
            "emotional_valence": 0.0,
        },
        {
            "memory_id": 2,
            "content": "gamma delta",
            "score": 1.0,
            "importance": 1.0,
            "emotional_valence": 0.9,
        },
    ]
    out = rp.attentional_focus_rerank(cands, "totally unrelated cue")
    assert out[0]["memory_id"] == 2
    assert out[0]["score"] > out[1]["score"]


# ── Identity: uniform / no-signal attention leaves ordering unchanged ────────
def test_no_signal_is_identity_scores_and_order():
    # Zero query overlap, equal (absent) salience → equal logits → uniform
    # softmax → every factor exactly 1.0.
    before = [
        {"memory_id": 1, "content": "alpha beta gamma", "score": 0.8},
        {"memory_id": 2, "content": "delta epsilon zeta", "score": 0.6},
        {"memory_id": 3, "content": "eta theta iota", "score": 0.4},
    ]
    out = rp.attentional_focus_rerank(copy.deepcopy(before), "wholly unrelated words")
    assert [c["memory_id"] for c in out] == [1, 2, 3]
    for o, b in zip(out, before):
        assert abs(o["score"] - b["score"]) < 1e-12


def test_uniform_salience_and_no_query_is_identity():
    # Equal salience across items with no query match → uniform distribution.
    before = [
        {
            "memory_id": 1,
            "content": "one",
            "score": 0.9,
            "importance": 0.5,
            "emotional_valence": 0.1,
        },
        {
            "memory_id": 2,
            "content": "two",
            "score": 0.7,
            "importance": 0.5,
            "emotional_valence": 0.1,
        },
    ]
    out = rp.attentional_focus_rerank(copy.deepcopy(before), "")  # empty query
    assert [c["memory_id"] for c in out] == [1, 2]
    for o, b in zip(out, before):
        assert abs(o["score"] - b["score"]) < 1e-12


# ── Recall is NOT truncated to the Cowan working-set ceiling ─────────────────
def test_recall_not_truncated_to_focus_capacity():
    n = FOCUS_CAPACITY_DEFAULT * 3  # well above the Cowan ceiling (4)
    cands = [
        {"memory_id": i, "content": f"decay note {i}", "score": 1.0 - 0.01 * i}
        for i in range(n)
    ]
    out = rp.attentional_focus_rerank(cands, "decay note")
    assert len(out) == n  # every candidate survives — no capacity cap
    assert {c["memory_id"] for c in out} == set(range(n))


# ── Ablation guard ──────────────────────────────────────────────────────────
def test_ablation_guard_disables():
    os.environ["CORTEX_ABLATE_ATTENTIONAL_CONTROL"] = "1"
    try:
        out = rp.attentional_focus_rerank(_cands(), "memory decay half-life")
        assert [c["memory_id"] for c in out] == [1, 2]
        assert out[0]["score"] == 0.60 and out[1]["score"] == 0.55
    finally:
        del os.environ["CORTEX_ABLATE_ATTENTIONAL_CONTROL"]


# ── Degenerate inputs ───────────────────────────────────────────────────────
def test_single_candidate_noop():
    cands = [{"memory_id": 1, "content": "decay", "score": 0.5}]
    out = rp.attentional_focus_rerank(cands, "decay")
    assert out[0]["score"] == 0.5  # <2 candidates → untouched


def test_empty_is_noop():
    assert rp.attentional_focus_rerank([], "anything") == []


def test_bounded_nudge_does_not_override_strong_match():
    # A much stronger content score stays ahead despite the other being the
    # attention winner — weight 0.15 is too small to close a large gap.
    cands = [
        {"memory_id": 1, "content": "irrelevant chatter", "score": 2.0},
        {"memory_id": 2, "content": "memory decay half-life", "score": 1.0},
    ]
    out = rp.attentional_focus_rerank(cands, "memory decay half-life")
    assert out[0]["memory_id"] == 1  # strong match holds the top


def test_reuses_allocate_attention(monkeypatch):
    # The stage must delegate to A1's pure allocate_attention, not reimplement.
    # Patch the name where recall_pipeline binds it: the import is at module
    # top (#197 family 4), so patching the defining module no longer reaches
    # the already-bound reference.
    called = {"n": 0}

    real = rp.allocate_attention

    def _spy(*a, **k):
        called["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(rp, "allocate_attention", _spy)
    rp.attentional_focus_rerank(_cands(), "memory decay half-life")
    assert called["n"] == 1
