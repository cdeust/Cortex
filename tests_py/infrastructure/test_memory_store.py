"""Tests for mcp_server.infrastructure.memory_store — PostgreSQL memory engine."""

import pytest

from mcp_server.infrastructure.memory_store import MemoryStore


@pytest.fixture()
def store():
    """Create a fresh store and clean up test data after each test."""
    s = MemoryStore()
    yield s
    # Clean up all test data
    s._conn.execute("DELETE FROM relationships")
    s._conn.execute("DELETE FROM entities")
    s._conn.execute("DELETE FROM memory_archives")
    s._conn.execute("DELETE FROM consolidation_log")
    s._conn.execute("DELETE FROM prospective_memories")
    s._conn.execute("DELETE FROM checkpoints")
    s._conn.execute("DELETE FROM engram_slots")
    s._conn.execute("DELETE FROM memories")
    s._conn.commit()
    s.close()


class TestMemoryStoreLifecycle:
    def test_connects_to_pg(self, store):
        assert store.has_vec is True

    def test_schema_idempotent(self, store):
        store2 = MemoryStore()
        assert store2.has_vec is True
        store2.close()


class TestMemoryCRUD:
    def test_insert_and_get(self, store):
        mem_id = store.insert_memory(
            {
                "content": "Test memory content",
                "tags": ["test", "unit"],
                "domain": "testing",
                "importance": 0.8,
            }
        )
        assert mem_id > 0
        mem = store.get_memory(mem_id)
        assert mem is not None
        assert mem["content"] == "Test memory content"
        assert mem["domain"] == "testing"
        assert mem["importance"] == 0.8

    def test_get_nonexistent(self, store):
        assert store.get_memory(999999) is None

    def test_delete_memory(self, store):
        mem_id = store.insert_memory({"content": "to delete"})
        assert store.delete_memory(mem_id) is True
        assert store.get_memory(mem_id) is None
        assert store.delete_memory(999999) is False

    def test_update_heat(self, store):
        mem_id = store.insert_memory({"content": "heat test", "heat": 1.0})
        store.update_memory_heat(mem_id, 0.5)
        mem = store.get_memory(mem_id)
        assert abs(mem["heat"] - 0.5) < 1e-6

    def test_update_access(self, store):
        mem_id = store.insert_memory({"content": "access test"})
        store.update_memory_access(mem_id)
        mem = store.get_memory(mem_id)
        assert mem["access_count"] == 1
        store.update_memory_access(mem_id)
        mem = store.get_memory(mem_id)
        assert mem["access_count"] == 2

    def test_set_protected(self, store):
        mem_id = store.insert_memory({"content": "protect me"})
        store.set_memory_protected(mem_id, True)
        mem = store.get_memory(mem_id)
        assert mem["is_protected"] is True


class TestMemoryQueries:
    def test_get_memories_for_domain(self, store):
        store.insert_memory({"content": "dom A", "domain": "alpha", "heat": 0.8})
        store.insert_memory({"content": "dom B", "domain": "beta", "heat": 0.9})
        store.insert_memory({"content": "dom A2", "domain": "alpha", "heat": 0.7})
        results = store.get_memories_for_domain("alpha")
        assert len(results) == 2
        assert all(m["domain"] == "alpha" for m in results)

    def test_get_hot_memories(self, store):
        store.insert_memory({"content": "hot", "heat": 0.9})
        store.insert_memory({"content": "cold", "heat": 0.1})
        store.insert_memory({"content": "warm", "heat": 0.8})
        results = store.get_hot_memories(min_heat=0.7)
        assert len(results) == 2

    def test_count_memories(self, store):
        store.insert_memory({"content": "a", "store_type": "episodic"})
        store.insert_memory({"content": "b", "store_type": "semantic"})
        counts = store.count_memories()
        assert counts["total"] >= 2
        assert counts["episodic"] >= 1
        assert counts["semantic"] >= 1


class TestFTSSearch:
    def test_basic_fts_search(self, store):
        mid = store.insert_memory({"content": "Python machine learning tutorial"})
        store.insert_memory({"content": "JavaScript React framework"})
        results = store.search_fts("Python")
        assert len(results) >= 1
        assert any(r[0] == mid for r in results)

    def test_no_results(self, store):
        store.insert_memory({"content": "hello world"})
        results = store.search_fts("nonexistent_unique_xyz")
        assert len(results) == 0


class TestProspectiveMemory:
    def test_insert_and_get_active(self, store):
        pm_id = store.insert_prospective_memory(
            {
                "content": "Remember to fix the parser",
                "trigger_condition": "parser fix",
                "trigger_type": "keyword_match",
            }
        )
        assert pm_id > 0
        active = store.get_active_prospective_memories()
        assert any(p["content"] == "Remember to fix the parser" for p in active)

    def test_trigger_and_deactivate(self, store):
        pm_id = store.insert_prospective_memory(
            {
                "content": "task",
                "trigger_condition": "cond",
                "trigger_type": "keyword_match",
            }
        )
        store.trigger_prospective_memory(pm_id)
        store.deactivate_prospective_memory(pm_id)


class TestCheckpoints:
    def test_insert_and_get(self, store):
        cp_id = store.insert_checkpoint(
            {
                "session_id": "test-session",
                "current_task": "writing tests",
                "files_being_edited": ["test.py"],
            }
        )
        assert cp_id > 0
        cp = store.get_active_checkpoint()
        assert cp is not None
        assert cp["current_task"] == "writing tests"

    def test_new_checkpoint_deactivates_old(self, store):
        store.insert_checkpoint({"current_task": "task 1"})
        store.insert_checkpoint({"current_task": "task 2"})
        cp = store.get_active_checkpoint()
        assert cp["current_task"] == "task 2"


class TestEntities:
    def test_insert_and_get(self, store):
        eid = store.insert_entity(
            {"name": "PostgreSQL", "type": "technology", "domain": "db"}
        )
        assert eid > 0
        entity = store.get_entity_by_name("PostgreSQL")
        assert entity is not None
        assert entity["type"] == "technology"

    def test_count_entities(self, store):
        store.insert_entity({"name": "A_test", "type": "t"})
        store.insert_entity({"name": "B_test", "type": "t"})
        assert store.count_entities() >= 2


class TestRelationships:
    def test_insert_and_count(self, store):
        e1 = store.insert_entity({"name": "A_rel", "type": "t"})
        e2 = store.insert_entity({"name": "B_rel", "type": "t"})
        rid = store.insert_relationship(
            {
                "source_entity_id": e1,
                "target_entity_id": e2,
                "relationship_type": "uses",
            }
        )
        assert rid > 0
        assert store.count_relationships() >= 1


class TestEngramSlots:
    def test_init_and_get_slots(self, store):
        store.init_engram_slots(5)
        slots = store.get_all_engram_slots()
        assert len(slots) >= 5

    def test_update_slot(self, store):
        store.init_engram_slots(3)
        store.update_engram_slot(
            1, excitability=0.9, last_activated="2024-01-01T00:00:00Z"
        )
        slot = store.get_engram_slot(1)
        assert abs(slot["excitability"] - 0.9) < 1e-6

    def test_assign_memory_to_slot(self, store):
        store.init_engram_slots(3)
        mem_id = store.insert_memory({"content": "slotted"})
        store.assign_memory_slot(mem_id, 2)
        mems = store.get_memories_in_slot(2)
        assert any(m["content"] == "slotted" for m in mems)


class TestConsolidationLog:
    def test_log_and_retrieve_last(self, store):
        store.log_consolidation({"memories_added": 5, "duration_ms": 100})
        last = store.get_last_consolidation()
        assert last is not None


class TestArchive:
    def test_insert_archive(self, store):
        mem_id = store.insert_memory({"content": "original"})
        aid = store.insert_archive(
            {
                "original_memory_id": mem_id,
                "content": "archived version",
                "mismatch_score": 0.8,
                "archive_reason": "reconsolidation",
            }
        )
        assert aid > 0
