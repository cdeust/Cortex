"""Tests for core.attentional_control (A1 central executive / attention)."""

from __future__ import annotations

import math

import pytest

from mcp_server.core.attentional_control import (
    ATTENTION_TEMPERATURE,
    FOCUS_CAPACITY_DEFAULT,
    allocate_attention,
    attention_allocation_as_dict,
    in_focus_contents,
    relevance_score,
)


# ── Relevance scoring ───────────────────────────────────────────────────────
def test_relevance_full_coverage():
    assert relevance_score("decay half life", "the decay half life is long") == 1.0


def test_relevance_partial():
    r = relevance_score("decay half life", "the decay rate")
    assert 0.0 < r < 1.0


def test_relevance_empty():
    assert relevance_score("", "anything") == 0.0
    assert relevance_score("query", "") == 0.0


# ── Allocation basics ───────────────────────────────────────────────────────
def _items(*contents):
    return [{"content": c} for c in contents]


def test_empty_items():
    a = allocate_attention("q", [])
    assert a.focus == [] and a.weights == [] and a.entropy == 0.0


def test_weights_sum_to_one():
    a = allocate_attention("decay", _items("decay curve", "unrelated", "decay rate"))
    assert math.isclose(sum(a.weights), 1.0, rel_tol=1e-9)


def test_most_relevant_is_in_focus_first():
    items = _items(
        "the reranker alpha constant",
        "decay half life thermodynamics",  # matches query best
        "unrelated content here",
    )
    a = allocate_attention("decay half life", items)
    assert a.focus[0]["content"] == "decay half life thermodynamics"
    assert a.focus[0]["attention_weight"] == pytest.approx(max(a.weights), abs=1e-4)


def test_capacity_ceiling_limits_focus():
    items = _items(*[f"item {i} decay" for i in range(10)])
    a = allocate_attention("decay", items, capacity=4)
    assert len(a.focus) == 4
    assert a.overflow == 6
    assert a.capacity == 4


def test_fewer_items_than_capacity_all_in_focus():
    items = _items("a decay", "b decay")
    a = allocate_attention("decay", items, capacity=4)
    assert len(a.focus) == 2
    assert a.overflow == 0


# ── Temperature (top-down control) ──────────────────────────────────────────
def test_low_temperature_sharpens_focus():
    items = _items("decay strong match", "weak", "another weak one")
    sharp = allocate_attention("decay strong match", items, temperature=0.2)
    diffuse = allocate_attention("decay strong match", items, temperature=2.0)
    # Sharper spotlight -> lower entropy, higher peak weight.
    assert sharp.entropy < diffuse.entropy
    assert max(sharp.weights) > max(diffuse.weights)


# ── Bottom-up salience capture ──────────────────────────────────────────────
def test_salience_lets_unbidden_item_capture_focus():
    # Two items equally (ir)relevant to the query, one highly salient.
    items = [
        {"content": "neutral note", "importance": 0.0, "valence": 0.0},
        {"content": "neutral note", "importance": 1.0, "valence": 1.0},
    ]
    a = allocate_attention("something else", items, salience_weight=1.0)
    # The salient one wins the spotlight.
    assert a.focus[0]["importance"] == 1.0


def test_zero_salience_weight_is_purely_top_down():
    items = [
        {"content": "decay match", "importance": 0.0},
        {"content": "irrelevant", "importance": 1.0},
    ]
    a = allocate_attention("decay match", items, salience_weight=0.0)
    # With no salience term the query-matching item leads despite low importance.
    assert a.focus[0]["content"] == "decay match"


# ── Precomputed (semantic) scores ───────────────────────────────────────────
def test_precomputed_scores_override_lexical():
    items = _items("aaa", "bbb", "ccc")
    a = allocate_attention("", items, precomputed_scores=[0.1, 0.9, 0.2])
    assert a.focus[0]["content"] == "bbb"


def test_precomputed_length_mismatch_raises():
    with pytest.raises(ValueError):
        allocate_attention("q", _items("a", "b"), precomputed_scores=[0.5])


# ── Helpers / defaults ──────────────────────────────────────────────────────
def test_in_focus_contents_order():
    items = _items("low", "decay high match", "mid decay")
    a = allocate_attention("decay high match", items)
    assert in_focus_contents(a)[0] == "decay high match"


def test_defaults_sane():
    assert FOCUS_CAPACITY_DEFAULT == 4
    assert 0.0 < ATTENTION_TEMPERATURE <= 1.0


# ── attention_allocation_as_dict (issue #282: dataclass mutation blindspot) ──
def test_attention_allocation_as_dict_shape_and_rounding():
    items = _items("low", "decay high match", "mid decay")
    a = allocate_attention("decay high match", items)
    d = attention_allocation_as_dict(a)
    assert set(d) == {"focus", "weights", "entropy", "capacity", "overflow"}
    assert d["focus"] == a.focus
    assert d["weights"] == [round(w, 4) for w in a.weights]
    assert d["entropy"] == round(a.entropy, 4)
    assert d["capacity"] == a.capacity
    assert d["overflow"] == a.overflow
