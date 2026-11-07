"""ADR-0321: real tagging math follows entity evidence, not name coincidence."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from mcp_server.core import write_post_store as post


class EntityStore:
    def __init__(self):
        self.updates = []
        self.scan_options = None

    def get_entity_by_name(self, name):
        return {"id": 8, "name": "Redis"} if name.lower() == "redis" else None

    def get_all_entities(self, **kwargs):
        return [{"id": 8, "name": "Redis"}, {"id": None, "name": "unpersisted"}]

    def get_memories_mentioning_entity(self, name, **kwargs):
        assert kwargs == {"limit": 50, "heads_only": True}
        return [{"id": 2}]

    def get_hot_memories(self, **kwargs):
        self.scan_options = kwargs
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        return [
            {"id": 1},
            {"id": 2, "importance": 0.2, "heat": 0.2, "created_at": recent},
            {"id": 3, "importance": 0.2, "heat": 0.2, "created_at": recent},
        ]

    def update_memory_importance(self, memory_id, value):
        self.updates.append(("importance", memory_id, value))

    def update_memory_heat(self, memory_id, value):
        self.updates.append(("heat", memory_id, value))


def test_legacy_store_boosts_only_shared_head_and_excludes_new_memory():
    store = EntityStore()
    tagged = post.run_synaptic_tagging(1, 0.9, ["REDIS"], store)
    assert [t["memory_id"] for t in tagged] == [2]
    assert tagged[0]["matched_entities"] == ["redis"]
    assert store.updates == [("importance", 2, 0.45), ("heat", 2, 0.3)]
    assert store.scan_options == {"min_heat": 0.0, "limit": 50, "heads_only": True}


def test_bulk_entity_lookup_resolves_ids_to_normalized_names():
    store = EntityStore()
    store.find_shared_entities = Mock(return_value=[8])
    assert post._find_shared_entities(2, ["Redis", "missing"], store) == {"redis"}
    store.find_shared_entities.assert_called_once_with(2, [8])
    assert post._find_shared_entities(0, ["Redis"], store) == set()


@pytest.mark.parametrize(
    "failing_method", ["get_entity_by_name", "get_all_entities", "find_shared_entities"]
)
def test_lookup_failure_never_boosts_unproven_entity_matches(
    failing_method, monkeypatch
):
    store = EntityStore()
    setattr(store, failing_method, Mock(side_effect=RuntimeError("offline")))
    notes = Mock()
    monkeypatch.setattr(post.silent_failure, "note", notes)
    assert post.run_synaptic_tagging(1, 0.9, ["Redis"], store) == []
    assert store.updates == []
    assert notes.called
    assert any(
        "entity" in call.args[0] or "entities" in call.args[0]
        for call in notes.call_args_list
    )


def test_empty_entity_catalog_and_ineligible_events_do_not_touch_store():
    empty = SimpleNamespace(
        get_entity_by_name=lambda name: None, get_all_entities=lambda **kwargs: []
    )
    assert post._find_shared_entities(2, ["Redis"], empty) == set()
    assert post.run_synaptic_tagging(1, 0.2, ["Redis"], object()) == []
    assert post.run_synaptic_tagging(1, 0.9, [], object()) == []


def test_timestamp_accepts_legacy_naive_values_without_wall_clock_assertions(
    monkeypatch,
):
    instant = datetime(2026, 10, 1, tzinfo=timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant

    monkeypatch.setattr(post, "datetime", Clock)
    assert post._hours_since_creation("2026-09-30T22:00:00") == 2
    assert post._hours_since_creation("2026-09-30T22:00:00+00:00") == 2
    assert post._hours_since_creation("corrupt") == post._hours_since_creation("") == 0
