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
