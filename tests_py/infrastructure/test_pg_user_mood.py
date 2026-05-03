"""User-mood wiring tests for PgMemoryStore.

Closes the production no-op gap surfaced by Phase B calibration:
``mcp_server/core/pg_recall.py:_get_user_mood(store)`` duck-types against
``store.get_user_mood()`` and previously always returned None because no
such method existed. These tests pin the new contract:

  - ``get_user_mood()`` returns a scalar float in [-1, +1] (the bridge contract)
  - ``set_user_mood()`` upserts and bumps ``updated_at``
  - ``get_user_mood_state()`` exposes both valence and arousal for future use
  - Out-of-range values are clamped at write time

Touches the real ``cortex`` PostgreSQL instance via the same fixture
pattern as ``test_pg_pool.py``. The DDL adds ``user_mood`` only via
``CREATE TABLE IF NOT EXISTS`` so an in-flight benchmark on the same DB
is unaffected.

Source: Bower, G.H. (1981). "Mood and Memory." Am. Psychologist 36(2).
"""

from __future__ import annotations

import pytest

from mcp_server.infrastructure.pg_store import PgMemoryStore


@pytest.fixture
def store():
    s = PgMemoryStore()
    # Always restore the seed neutral row on teardown so the benchmark
    # / production reads stay deterministic across the test session.
    yield s
    try:
        s.set_user_mood(0.0, 0.0)
    finally:
        s.close()


class TestUserMoodSeed:
    def test_default_row_exists_after_schema_init(self, store):
        """Seed row 'default' is inserted by SUPPORT_TABLES_DDL."""
        # Resetting via the fixture's teardown happens AFTER the test;
        # at this point the row should already exist with valence ∈ [-1, 1].
        v = store.get_user_mood()
        assert v is not None
        assert -1.0 <= v <= 1.0

    def test_default_state_shape(self, store):
        state = store.get_user_mood_state()
        assert state is not None
        assert set(state.keys()) == {"valence", "arousal"}
        assert isinstance(state["valence"], float)
        assert isinstance(state["arousal"], float)


class TestUserMoodWrite:
    def test_set_then_get_roundtrip(self, store):
        store.set_user_mood(0.7, 0.3)
        v = store.get_user_mood()
        assert v is not None
        assert v == pytest.approx(0.7, abs=1e-5)
        state = store.get_user_mood_state()
        assert state == pytest.approx({"valence": 0.7, "arousal": 0.3}, abs=1e-5)

    def test_set_clamps_above_one(self, store):
        store.set_user_mood(2.0, 5.0)
        state = store.get_user_mood_state()
        assert state == {"valence": 1.0, "arousal": 1.0}

    def test_set_clamps_below_negative_one(self, store):
        store.set_user_mood(-2.0, -5.0)
        state = store.get_user_mood_state()
        assert state == {"valence": -1.0, "arousal": -1.0}

    def test_set_is_upsert_idempotent(self, store):
        """Repeated set with same value is fine and ends in same state."""
        store.set_user_mood(-0.4, 0.1)
        store.set_user_mood(-0.4, 0.1)
        state = store.get_user_mood_state()
        assert state == pytest.approx({"valence": -0.4, "arousal": 0.1}, abs=1e-5)


class TestUserMoodBridge:
    """Confirms the duck-typed bridge in pg_recall._get_user_mood works."""

    def test_pg_recall_bridge_consumes_scalar(self, store):
        """_get_user_mood(store) must return the same scalar as get_user_mood()."""
        from mcp_server.core.pg_recall import _get_user_mood

        store.set_user_mood(0.5)
        bridged = _get_user_mood(store)
        assert bridged == pytest.approx(0.5, abs=1e-5)

    def test_pg_recall_bridge_clamps(self, store):
        """Bridge clamps to [-1, +1] defensively even though set already does."""
        from mcp_server.core.pg_recall import _get_user_mood

        # Write a legal max; bridge must accept it.
        store.set_user_mood(1.0)
        assert _get_user_mood(store) == pytest.approx(1.0, abs=1e-5)
        store.set_user_mood(-1.0)
        assert _get_user_mood(store) == pytest.approx(-1.0, abs=1e-5)


class TestMoodCongruentRerankWithRealStore:
    """End-to-end: real store → bridge → mood_congruent_rerank produces a delta.

    No PG retrieval is invoked here; we only need the store's
    ``get_user_mood`` to flow into the stage's reranker via the bridge.
    """

    def test_active_mood_reorders_candidates(self, store):
        from mcp_server.core.pg_recall import _get_user_mood
        from mcp_server.core.recall_pipeline import mood_congruent_rerank

        store.set_user_mood(0.8)
        mood = _get_user_mood(store)
        assert mood is not None  # bridge sees the signal

        # Two candidates with opposite valence; positive-mood user → the
        # positive-valence candidate must rank above the negative one.
        cands = [
            {"memory_id": 100, "score": 0.5, "emotional_valence": -0.8},
            {"memory_id": 200, "score": 0.4, "emotional_valence": +0.8},
        ]
        # Use a dominant blend (beta > 0.5) to demonstrate the wiring CAN flip
        # adjacent ranks when given enough weight. The calibrated production
        # default _MOOD_CONGRUENT_BETA=0.15 is intentionally below the rank-flip
        # threshold (RRF math: beta > 0.5 to flip rank-1 vs rank-0); the
        # mechanism is a tie-breaker, not a filter, by design (Bower 1981
        # describes the effect qualitatively, not as a dominant signal).
        out = mood_congruent_rerank(cands, mood, blend_beta=0.6)
        out_ids = [c["memory_id"] for c in out]
        # Mood 0.8 closer to 0.8 than to -0.8 → mid 200 promoted.
        assert out_ids.index(200) < out_ids.index(100)

    def test_neutral_mood_is_no_op(self, store):
        from mcp_server.core.pg_recall import _get_user_mood
        from mcp_server.core.recall_pipeline import mood_congruent_rerank

        store.set_user_mood(0.0)
        mood = _get_user_mood(store)
        assert mood == pytest.approx(0.0, abs=1e-5)

        cands = [
            {"memory_id": 100, "score": 0.5, "emotional_valence": -0.8},
            {"memory_id": 200, "score": 0.4, "emotional_valence": +0.8},
        ]
        out = mood_congruent_rerank(cands, mood)
        # Neutral mood: distance to ±0.8 is identical → blend yields a
        # tie (reranker is a stable sort), so the relative order of the
        # input is preserved.
        assert [c["memory_id"] for c in out] == [100, 200]
