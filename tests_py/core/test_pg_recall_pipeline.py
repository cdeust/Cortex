"""Tests for the post-WRRF recall pipeline (HOPFIELD/HDC/SA/DENDRITIC).

Each mechanism has two paths:

  - Enabled (default): the stage runs and (in the fixtures used here)
    visibly reorders or expands the candidate list.
  - Disabled (``CORTEX_ABLATE_<MECH>=1``): the stage returns the input
    unchanged. This is the verification the audit relies on — the env
    var must produce a wiring-level no-op.

Fixtures use small synthetic candidate pools and a fake store with the
methods the pipeline actually calls (``get_memory``,
``spread_activation_memories``). No real PG is touched.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

import numpy as np
import pytest

from mcp_server.core.recall_pipeline import (
    dendritic_modulate,
    emotional_retrieval_rerank,
    hdc_rerank,
    hopfield_complete,
    mood_congruent_rerank,
    spreading_activation_expand,
)


# ── Fixtures ────────────────────────────────────────────────────────────


@contextmanager
def _ablate(env_name: str):
    """Set CORTEX_ABLATE_<MECH>=1 for the duration of a block."""
    prev = os.environ.get(env_name)
    os.environ[env_name] = "1"
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop(env_name, None)
        else:
            os.environ[env_name] = prev


def _make_emb(dim: int, seed: int) -> bytes:
    """Deterministic L2-normalized float32 embedding."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    v = v / np.linalg.norm(v)
    return v.tobytes()


class _FakeStore:
    """Minimal store stub providing the methods the pipeline needs."""

    def __init__(self, memories: dict[int, dict], sa_response=None) -> None:
        self._mems = memories
        self._sa_response = sa_response or []

    def get_memory(self, mid: int):
        return self._mems.get(mid)

    def spread_activation_memories(self, **kwargs):
        return list(self._sa_response)


def _make_candidates(n: int) -> list[dict]:
    return [
        {
            "memory_id": i,
            "content": f"candidate {i} content with shared token retrieval"
            + (" extra special" if i == 2 else ""),
            "score": 1.0 / (i + 1),
            "heat": 0.5,
            "tags": ["a", "b"] if i % 2 == 0 else ["c"],
            "domain": "test",
            "created_at": "2026-04-30T00:00:00Z",
        }
        for n_ in [n]
        for i in range(n_)
    ]


# ── HOPFIELD ────────────────────────────────────────────────────────────


def test_hopfield_disabled_returns_input_unchanged():
    cands = _make_candidates(5)
    q_emb = _make_emb(384, 0)
    store = _FakeStore(
        {
            c["memory_id"]: {**c, "embedding": _make_emb(384, c["memory_id"])}
            for c in cands
        }
    )
    with _ablate("CORTEX_ABLATE_HOPFIELD"):
        out = hopfield_complete(cands, q_emb, store, embedding_dim=384)
    assert out == cands


def test_hopfield_enabled_reorders_using_attention():
    cands = _make_candidates(5)
    q_emb = _make_emb(384, 42)
    # Embed last candidate to be identical to the query → strongest attention.
    # Hopfield should pull it up from rank 4 toward the top under RRF blend.
    embs = {c["memory_id"]: _make_emb(384, c["memory_id"]) for c in cands}
    embs[4] = q_emb
    store = _FakeStore(
        {c["memory_id"]: {**c, "embedding": embs[c["memory_id"]]} for c in cands}
    )
    out = hopfield_complete(cands, q_emb, store, embedding_dim=384)
    out_ids = [c["memory_id"] for c in out]
    # Candidate 4 must improve its rank (started at 4, must end strictly higher).
    assert out_ids.index(4) < 4
    # Scores must have been recomputed (RRF returns floats < 1).
    assert all(c["score"] < 1.0 for c in out)


def test_hopfield_handles_missing_embeddings():
    cands = _make_candidates(3)
    q_emb = _make_emb(384, 1)
    store = _FakeStore({c["memory_id"]: dict(c) for c in cands})  # no embeddings
    out = hopfield_complete(cands, q_emb, store, embedding_dim=384)
    assert out == cands


# ── HDC ─────────────────────────────────────────────────────────────────


def test_hdc_disabled_returns_input_unchanged():
    cands = _make_candidates(5)
    with _ablate("CORTEX_ABLATE_HDC"):
        out = hdc_rerank(cands, "candidate retrieval shared")
    assert out == cands


def test_hdc_enabled_reorders_by_token_overlap():
    cands = _make_candidates(5)
    # Inject one candidate that's a near-perfect token match
    cands.append(
        {
            "memory_id": 99,
            "content": "candidate retrieval shared token extra special",
            "score": 0.05,
            "heat": 0.5,
            "tags": ["c"],
            "domain": "test",
            "created_at": "2026-04-30T00:00:00Z",
        }
    )
    out = hdc_rerank(cands, "extra special candidate retrieval shared token")
    out_ids = [c["memory_id"] for c in out]
    # The HDC-similar candidate must rise above its starting position.
    assert out_ids.index(99) < len(cands) - 1


# ── SPREADING_ACTIVATION ────────────────────────────────────────────────


def test_sa_disabled_returns_input_unchanged():
    cands = _make_candidates(3)
    store = _FakeStore({c["memory_id"]: c for c in cands}, sa_response=[(99, 0.9)])
    with _ablate("CORTEX_ABLATE_SPREADING_ACTIVATION"):
        out = spreading_activation_expand(cands, "query terms", store)
    assert out == cands


def test_sa_enabled_injects_new_candidate_from_graph():
    cands = _make_candidates(3)
    new_mem = {
        "id": 99,
        "content": "graph-discovered memory",
        "heat": 0.7,
        "domain": "test",
        "tags": [],
        "created_at": "2026-04-30T00:00:00Z",
    }
    store = _FakeStore(
        {**{c["memory_id"]: c for c in cands}, 99: new_mem},
        sa_response=[(99, 0.9), (0, 0.4)],
    )
    out = spreading_activation_expand(cands, "query expand entity terms", store)
    out_ids = [c["memory_id"] for c in out]
    assert 99 in out_ids  # SA injected the new memory


def test_sa_no_terms_returns_input_unchanged():
    cands = _make_candidates(2)
    store = _FakeStore({c["memory_id"]: c for c in cands}, sa_response=[(99, 0.9)])
    out = spreading_activation_expand(cands, "a b", store)  # all words ≤ 2 chars
    assert out == cands


# ── DENDRITIC_CLUSTERS ──────────────────────────────────────────────────


def test_dendritic_disabled_returns_input_unchanged():
    cands = _make_candidates(4)
    with _ablate("CORTEX_ABLATE_DENDRITIC_CLUSTERS"):
        out = dendritic_modulate(cands, "shared token retrieval")
    assert out == cands


def test_dendritic_enabled_perturbs_score_within_bounds():
    cands = _make_candidates(4)
    out = dendritic_modulate(cands, "shared token retrieval candidate")
    # Each candidate's score is multiplied by a factor in [1-DELTA, 1+DELTA].
    # DELTA = 0.10 (recall_pipeline._DENDRITIC_DELTA), so the ratio is in
    # [0.9, 1.1].
    by_id = {c["memory_id"]: c for c in cands}
    for c_out in out:
        old = by_id[c_out["memory_id"]]["score"]
        new = c_out["score"]
        if old > 0:
            ratio = new / old
            assert 0.9 - 1e-6 <= ratio <= 1.1 + 1e-6


def test_dendritic_no_query_tokens_returns_input_unchanged():
    cands = _make_candidates(3)
    out = dendritic_modulate(cands, "a b c")  # all tokens ≤ 2 chars
    assert out == cands


# ── Composition smoke test ──────────────────────────────────────────────


def test_pipeline_all_disabled_is_identity():
    """All four ablated → final list identical to input."""
    cands = _make_candidates(5)
    q_emb = _make_emb(384, 1)
    store = _FakeStore(
        {
            c["memory_id"]: {**c, "embedding": _make_emb(384, c["memory_id"])}
            for c in cands
        },
        sa_response=[(99, 0.9)],
    )
    env_vars = (
        "CORTEX_ABLATE_HOPFIELD",
        "CORTEX_ABLATE_HDC",
        "CORTEX_ABLATE_SPREADING_ACTIVATION",
        "CORTEX_ABLATE_DENDRITIC_CLUSTERS",
    )
    prev = {k: os.environ.get(k) for k in env_vars}
    try:
        for k in env_vars:
            os.environ[k] = "1"
        out = hopfield_complete(cands, q_emb, store, embedding_dim=384)
        out = hdc_rerank(out, "shared retrieval candidate")
        out = spreading_activation_expand(out, "shared retrieval candidate", store)
        out = dendritic_modulate(out, "shared retrieval candidate")
    finally:
        for k, v in prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    assert out == cands


# ── Bulk-fetch path: Hopfield uses store.get_embeddings_for_memories ────


class _BulkStore(_FakeStore):
    """Store stub that exposes the bulk embedding API (single round trip)."""

    def __init__(self, memories, sa_response=None):
        super().__init__(memories, sa_response)
        self.bulk_calls = 0
        self.per_id_calls = 0

    def get_memory(self, mid):
        self.per_id_calls += 1
        return super().get_memory(mid)

    def get_embeddings_for_memories(self, ids):
        self.bulk_calls += 1
        return {
            mid: m["embedding"]
            for mid in ids
            if (m := self._mems.get(mid)) and m.get("embedding")
        }


def test_hopfield_uses_bulk_embedding_api_when_available():
    """Hopfield must call the bulk API exactly once and never per-id."""
    cands = _make_candidates(5)
    q_emb = _make_emb(384, 7)
    store = _BulkStore(
        {
            c["memory_id"]: {**c, "embedding": _make_emb(384, c["memory_id"])}
            for c in cands
        }
    )
    out = hopfield_complete(cands, q_emb, store, embedding_dim=384)
    assert store.bulk_calls == 1, "expected exactly one bulk PG round trip"
    assert store.per_id_calls == 0, "must not fall back to per-id get_memory"
    # Sanity: pipeline still produced a list of the same length.
    assert len(out) == len(cands)


# ── Real entity-set Jaccard for the dendritic stage ─────────────────────


class _EntityStore:
    """Store stub for dendritic_modulate's real entity-graph path."""

    def __init__(
        self, query_entity_ids: dict[str, int], memory_entity_ids: dict[int, set[int]]
    ):
        self._q_ent = query_entity_ids
        self._mem_ent = memory_entity_ids

    def get_entity_by_name(self, name):
        eid = self._q_ent.get(name)
        return {"id": eid} if eid is not None else None

    def get_entity_ids_for_memories(self, ids):
        return {mid: self._mem_ent[mid] for mid in ids if mid in self._mem_ent}


def test_dendritic_uses_real_entity_jaccard_when_store_supports_it():
    """Candidate sharing the resolved query entity must rank above a peer."""
    cands = _make_candidates(3)
    # Query has one CamelCase entity ("FooBar"), resolved to entity_id=42.
    # Candidate 1 shares it; candidate 0 has no entities; candidate 2 has
    # an unrelated entity (99).
    store = _EntityStore(
        query_entity_ids={"FooBar": 42},
        memory_entity_ids={0: set(), 1: {42}, 2: {99}},
    )
    out = dendritic_modulate(cands, "search for FooBar implementation", store)
    out_by_id = {c["memory_id"]: c for c in out}
    cands_by_id = {c["memory_id"]: c for c in cands}
    # Candidate 1's score must be strictly bumped above its starting score
    # (entity Jaccard = 1.0 / 1.0 = 1.0 → factor 1 + DELTA).
    assert out_by_id[1]["score"] > cands_by_id[1]["score"]
    # Candidates 0 and 2 must NOT receive a positive bump
    # (entity Jaccard with query is 0).
    assert out_by_id[0]["score"] <= cands_by_id[0]["score"]
    assert out_by_id[2]["score"] <= cands_by_id[2]["score"]
    # Same-shape contract: every key on the input candidate is preserved.
    for c_out in out:
        assert set(cands_by_id[c_out["memory_id"]]) <= set(c_out)


def test_dendritic_falls_back_to_token_jaccard_when_query_unresolvable():
    """Natural-language query (no CamelCase) → token-Jaccard fallback."""
    cands = _make_candidates(4)
    # Store supports the bulk API but query has nothing to resolve.
    store = _EntityStore(query_entity_ids={}, memory_entity_ids={})
    out = dendritic_modulate(cands, "shared token retrieval candidate", store)
    # Same-shape result; modulation produced the same bounded ratio
    # documented in test_dendritic_enabled_perturbs_score_within_bounds.
    by_id = {c["memory_id"]: c for c in cands}
    for c_out in out:
        old = by_id[c_out["memory_id"]]["score"]
        new = c_out["score"]
        if old > 0:
            assert 0.9 - 1e-6 <= new / old <= 1.1 + 1e-6


# ── EMOTIONAL_RETRIEVAL ─────────────────────────────────────────────────


def _emo_candidates() -> list[dict]:
    """Candidates spanning the valence range [-0.8, +0.8]."""
    valences = [+0.8, -0.6, +0.1, -0.8, +0.5]
    return [
        {
            "memory_id": i,
            "content": f"mem {i}",
            "score": 1.0 / (i + 1),
            "heat": 0.5,
            "tags": [],
            "domain": "test",
            "created_at": "2026-04-30T00:00:00Z",
            "emotional_valence": v,
        }
        for i, v in enumerate(valences)
    ]


def test_emotional_retrieval_active_positive_query_promotes_positive():
    """A positive-valence query must rank positive candidates above negative."""
    cands = _emo_candidates()
    # "fixed deployed shipped excellent" → strongly positive VADER compound
    out = emotional_retrieval_rerank(
        cands, "fixed deployed shipped excellent breakthrough"
    )
    out_ids = [c["memory_id"] for c in out]
    # Candidate 0 (valence +0.8) and 4 (+0.5) must outrank 3 (-0.8) and 1 (-0.6).
    assert out_ids.index(0) < out_ids.index(3)
    assert out_ids.index(0) < out_ids.index(1)
    # Score type unchanged (float), and all keys preserved.
    by_id = {c["memory_id"]: c for c in cands}
    for c_out in out:
        assert isinstance(c_out["score"], float)
        assert set(by_id[c_out["memory_id"]]) <= set(c_out)


def test_emotional_retrieval_neutral_query_returns_identity():
    """A neutral query (|VADER compound| < floor) is a no-op."""
    cands = _emo_candidates()
    # "the file path module import" — zero lexicon hits → compound = 0.0
    out = emotional_retrieval_rerank(cands, "the file path module import")
    assert out == cands


def test_emotional_retrieval_disabled_returns_identity():
    """CORTEX_ABLATE_EMOTIONAL_RETRIEVAL=1 must short-circuit the rerank."""
    cands = _emo_candidates()
    with _ablate("CORTEX_ABLATE_EMOTIONAL_RETRIEVAL"):
        out = emotional_retrieval_rerank(cands, "fixed deployed shipped excellent")
    assert out == cands


# ── MOOD_CONGRUENT_RERANK ───────────────────────────────────────────────


def test_mood_congruent_no_mood_returns_identity():
    """user_mood=None → stage is identity. We do NOT fabricate a mood."""
    cands = _emo_candidates()
    out = mood_congruent_rerank(cands, None)
    assert out == cands


def test_mood_congruent_disabled_returns_identity():
    """CORTEX_ABLATE_MOOD_CONGRUENT_RERANK=1 must short-circuit."""
    cands = _emo_candidates()
    with _ablate("CORTEX_ABLATE_MOOD_CONGRUENT_RERANK"):
        out = mood_congruent_rerank(cands, +0.7)
    assert out == cands


def test_mood_congruent_active_promotes_congruent_valence():
    """Positive user mood → positive-valence candidates get a rank boost."""
    cands = _emo_candidates()
    out = mood_congruent_rerank(cands, user_mood=+0.7)
    out_ids = [c["memory_id"] for c in out]
    # Candidate 0 (+0.8) is closest to mood +0.7 → must rank above 3 (-0.8).
    assert out_ids.index(0) < out_ids.index(3)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
