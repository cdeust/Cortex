"""Tests for mcp_server.core.decay_cycle — periodic heat decay."""

from datetime import datetime, timezone, timedelta

from mcp_server.core.decay_cycle import (
    compute_decay_updates,
    compute_entity_decay,
)


class TestComputeDecayUpdates:
    def test_recent_memories_no_decay(self):
        now = datetime.now(timezone.utc)
        mems = [
            {
                "id": 1,
                "heat": 1.0,
                "last_accessed": now.isoformat(),
                "importance": 0.5,
                "emotional_valence": 0.0,
                "confidence": 1.0,
            }
        ]
        updates = compute_decay_updates(mems, now=now)
        assert len(updates) == 0  # No time elapsed

    def test_old_memories_decay(self):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(hours=24)).isoformat()
        mems = [
            {
                "id": 1,
                "heat": 1.0,
                "last_accessed": old,
                "importance": 0.3,
                "emotional_valence": 0.0,
                "confidence": 1.0,
            }
        ]
        updates = compute_decay_updates(mems, now=now)
        assert len(updates) == 1
        assert updates[0][0] == 1
        assert updates[0][1] < 1.0

    def test_protected_skipped(self):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(hours=24)).isoformat()
        mems = [
            {
                "id": 1,
                "heat": 1.0,
                "last_accessed": old,
                "is_protected": True,
            }
        ]
        updates = compute_decay_updates(mems, now=now)
        assert len(updates) == 0

    def test_already_cold_skipped(self):
        now = datetime.now(timezone.utc)
        mems = [
            {
                "id": 1,
                "heat": 0.01,
                "last_accessed": now.isoformat(),
            }
        ]
        updates = compute_decay_updates(mems, now=now, cold_threshold=0.05)
        assert len(updates) == 0

    def test_important_decays_slower(self):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(hours=48)).isoformat()
        normal = [
            {
                "id": 1,
                "heat": 1.0,
                "last_accessed": old,
                "importance": 0.3,
                "emotional_valence": 0.0,
                "confidence": 1.0,
            }
        ]
        important = [
            {
                "id": 2,
                "heat": 1.0,
                "last_accessed": old,
                "importance": 0.9,
                "emotional_valence": 0.0,
                "confidence": 1.0,
            }
        ]
        n_updates = compute_decay_updates(normal, now=now)
        i_updates = compute_decay_updates(important, now=now)
        assert i_updates[0][1] > n_updates[0][1]

    def test_multiple_memories(self):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(hours=12)).isoformat()
        mems = [
            {
                "id": 1,
                "heat": 0.9,
                "last_accessed": old,
                "importance": 0.5,
                "emotional_valence": 0.0,
                "confidence": 1.0,
            },
            {
                "id": 2,
                "heat": 0.5,
                "last_accessed": old,
                "importance": 0.3,
                "emotional_valence": 0.0,
                "confidence": 1.0,
            },
        ]
        updates = compute_decay_updates(mems, now=now)
        assert len(updates) == 2


class TestComputeEntityDecay:
    def test_recent_entities_no_decay(self):
        now = datetime.now(timezone.utc)
        entities = [{"id": 1, "heat": 0.8, "last_accessed": now.isoformat()}]
        updates = compute_entity_decay(entities, now=now)
        assert len(updates) == 0

    def test_old_entities_decay(self):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(hours=48)).isoformat()
        entities = [{"id": 1, "heat": 0.8, "last_accessed": old}]
        updates = compute_entity_decay(entities, now=now)
        assert len(updates) == 1
        assert updates[0][1] < 0.8

    def test_cold_entities_skipped(self):
        now = datetime.now(timezone.utc)
        entities = [{"id": 1, "heat": 0.01, "last_accessed": now.isoformat()}]
        updates = compute_entity_decay(entities, now=now, cold_threshold=0.05)
        assert len(updates) == 0


class TestIngestRelativeCadence:
    """Regression: cadence reasoning uses ingested_at, not created_at.

    Source: tasks/e1-v3-locomo-smoke-finding.md.
    """

    def test_adaptive_decay_uses_ingested_at_not_created_at(self):
        """Backfilled memory with backdated created_at must NOT collapse.

        ACT-R lifetime L = elapsed time since acquisition by THIS system.
        For a 3-year-old created_at but a fresh ingested_at, L should be
        ~hours (just-ingested), not ~3-years. Otherwise the ACT-R base
        level B = ln(n) - 0.5*ln(L) sinks far below threshold and heat
        collapses to near-zero on first decay pass.
        """
        now = datetime.now(timezone.utc)
        years_ago = (now - timedelta(days=365 * 3)).isoformat()
        # Just-ingested 5 minutes ago.
        fresh_ingest = (now - timedelta(minutes=5)).isoformat()
        mems = [
            {
                "id": 1,
                "heat": 0.8,
                "created_at": years_ago,
                "ingested_at": fresh_ingest,
                "last_accessed": fresh_ingest,
                "access_count": 1,
                "importance": 0.5,
                "emotional_valence": 0.0,
                "confidence": 1.0,
            }
        ]
        updates = compute_decay_updates(mems, now=now, adaptive_decay=True)
        # If cadence used created_at, lifetime would be ~26 280 hours and
        # heat would collapse to near-zero (<<0.1). With ingested_at it
        # stays close to its initial 0.8.
        if updates:
            new_heat = updates[0][1]
            assert new_heat > 0.4, (
                f"freshly-ingested backdated memory collapsed to {new_heat}"
            )

    def test_legacy_dict_falls_back_to_created_at(self):
        """Pre-migration rows (no ingested_at) keep the old behaviour."""
        now = datetime.now(timezone.utc)
        old = (now - timedelta(hours=48)).isoformat()
        mems = [
            {
                "id": 1,
                "heat": 1.0,
                "last_accessed": old,
                "created_at": old,
                "importance": 0.3,
                "emotional_valence": 0.0,
                "confidence": 1.0,
            }
        ]
        updates = compute_decay_updates(mems, now=now)
        # Decays normally — fallback chain kept intact.
        assert len(updates) == 1
        assert updates[0][1] < 1.0
