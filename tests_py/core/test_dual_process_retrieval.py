"""Unit tests for C2 dual-process retrieval — the a-contextual familiarity gate.

Covers the pure-logic core (mcp_server/core/dual_process_retrieval.py):
  - familiarity_score = max similarity (high vs low, empty);
  - assess_familiarity scalars (max/mean/margin, singleton, empty);
  - recollection_needed decision (overwhelming+dominant → not needed; marginal,
    diffuse, low, non-vector, empty → needed);
  - triage annotates each candidate without reordering, and the shortcut is
    opt-in only.

No Postgres / embeddings — the core takes a plain similarity list.
"""

from __future__ import annotations

from mcp_server.core.dual_process_retrieval import (
    FAMILIARITY_MARGIN,
    FAMILIARITY_THRESHOLD,
    METHOD_EMPTY,
    METHOD_SCORE_PROXY,
    METHOD_VECTOR,
    assess_familiarity,
    familiarity_score,
    familiarity_signal_as_dict,
    recollection_needed,
    triage,
)


# ── familiarity_score (the gate) ──────────────────────────────────────────────
def test_familiarity_high_when_a_candidate_matches():
    assert familiarity_score([0.2, 0.97, 0.5]) == 0.97


def test_familiarity_low_when_all_weak():
    assert familiarity_score([0.1, 0.2, 0.15]) == 0.2


def test_familiarity_empty_is_zero():
    assert familiarity_score([]) == 0.0


# ── assess_familiarity (the full signal) ──────────────────────────────────────
def test_assess_scalars():
    sig = assess_familiarity([0.95, 0.80, 0.10])
    assert sig.familiarity == 0.95
    assert sig.n == 3
    assert sig.mean == (0.95 + 0.80 + 0.10) / 3
    assert abs(sig.margin - (0.95 - 0.80)) < 1e-9
    assert sig.method == METHOD_VECTOR


def test_assess_singleton_margin_equals_max():
    sig = assess_familiarity([0.93])
    assert sig.n == 1
    assert sig.familiarity == 0.93
    assert sig.margin == 0.93  # no competitor


def test_assess_empty_tagged():
    sig = assess_familiarity([])
    assert sig.n == 0
    assert sig.method == METHOD_EMPTY
    assert sig.familiarity == 0.0


# ── recollection_needed (the decision) ────────────────────────────────────────
def test_overwhelming_dominant_hit_is_sufficient():
    # max >= threshold AND clear margin → familiarity suffices, no recollection.
    sig = assess_familiarity([0.96, 0.60, 0.20])
    assert recollection_needed(sig) is False


def test_singleton_overwhelming_is_sufficient():
    sig = assess_familiarity([0.99])
    assert recollection_needed(sig) is False


def test_high_but_ambiguous_needs_recollection():
    # Two near-tied high matches: dominant fails → recollection needed.
    sig = assess_familiarity([0.96, 0.95, 0.30])
    assert sig.familiarity >= FAMILIARITY_THRESHOLD
    assert sig.margin < FAMILIARITY_MARGIN
    assert recollection_needed(sig) is True


def test_below_threshold_needs_recollection():
    sig = assess_familiarity([0.80, 0.30, 0.10])
    assert recollection_needed(sig) is True


def test_empty_needs_recollection():
    assert recollection_needed(assess_familiarity([])) is True


def test_non_vector_proxy_never_sufficient():
    # A score-proxy signal, even numerically overwhelming, may not skip recall.
    sig = assess_familiarity([0.99, 0.10], method=METHOD_SCORE_PROXY)
    assert recollection_needed(sig) is True


def test_threshold_boundary_is_inclusive():
    sig = assess_familiarity([FAMILIARITY_THRESHOLD, 0.10])
    assert recollection_needed(sig) is False


# ── triage (annotate + decide, opt-in shortcut) ───────────────────────────────
def _cands(*sims):
    return [
        {"memory_id": i, "content": f"m{i}", "score": s} for i, s in enumerate(sims)
    ]


def test_triage_annotates_without_reordering():
    sims = [0.30, 0.96, 0.50]
    cands = _cands(*sims)
    res = triage(cands, sims)
    # Order & membership preserved.
    assert [c["memory_id"] for c in res.candidates] == [0, 1, 2]
    # Per-candidate familiarity annotated.
    assert [c["familiarity"] for c in res.candidates] == [0.30, 0.96, 0.50]


def test_triage_default_never_shortcuts():
    sims = [0.99, 0.20]
    res = triage(_cands(*sims), sims)  # allow_shortcut defaults False
    assert res.recollection_needed is False  # familiarity IS sufficient
    assert res.shortcut is False  # but default does not license skipping


def test_triage_shortcut_opt_in_on_overwhelming_hit():
    sims = [0.99, 0.20]
    res = triage(_cands(*sims), sims, allow_shortcut=True)
    assert res.shortcut is True


def test_triage_shortcut_opt_in_but_marginal_stays_full():
    sims = [0.96, 0.95]  # ambiguous — recollection needed even with opt-in
    res = triage(_cands(*sims), sims, allow_shortcut=True)
    assert res.recollection_needed is True
    assert res.shortcut is False


def test_triage_misaligned_similarities_skips_annotation():
    cands = _cands(0.9, 0.8)
    res = triage(cands, [0.9])  # length mismatch
    assert all("familiarity" not in c for c in res.candidates)
    # Membership still intact.
    assert len(res.candidates) == 2


def test_triage_empty():
    res = triage([], [])
    assert res.candidates == []
    assert res.recollection_needed is True
    assert res.shortcut is False


# ── familiarity_signal_as_dict (issue #282: dataclass mutation blindspot) ────
def test_familiarity_signal_as_dict_rounds_and_shapes():
    # 7th-decimal precision on every similarity so round(x, 6) vs round(x, 7)
    # is observable for familiarity/mean/margin alike (issue #282 gap: a
    # 1-2 significant-digit fixture rounds identically at 6 vs 7 places).
    signal = assess_familiarity([0.9123456, 0.5198765, 0.2123456])
    d = familiarity_signal_as_dict(signal)
    assert set(d) == {"familiarity", "mean", "margin", "n", "method"}
    assert d["familiarity"] == round(signal.familiarity, 6)
    assert d["mean"] == round(signal.mean, 6)
    assert d["margin"] == round(signal.margin, 6)
    assert d["n"] == signal.n
    assert d["method"] == signal.method
