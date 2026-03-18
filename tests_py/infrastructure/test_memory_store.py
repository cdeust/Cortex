"""Tests for mcp_server.infrastructure.memory_store — SQLite memory engine."""

import tempfile
import os

from mcp_server.infrastructure.memory_store import MemoryStore


def _make_store(tmp_dir: str) -> MemoryStore:
    db_path = os.path.join(tmp_dir, "test_memory.db")
    return MemoryStore(db_path, embedding_dim=384)


class TestMemoryStoreLifecycle:
    def test_creates_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            assert os.path.exists(os.path.join(tmp, "test_memory.db"))
            store.close()

    def test_schema_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            store.close()
            # Reopening should not fail
            store2 = MemoryStore(os.path.join(tmp, "test_memory.db"))
            store2.close()


class TestMemoryCRUD:
    def test_insert_and_get(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
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
            store.close()

    def test_get_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            assert store.get_memory(9999) is None
            store.close()

    def test_delete_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            mem_id = store.insert_memory({"content": "to delete"})
            assert store.delete_memory(mem_id) is True
            assert store.get_memory(mem_id) is None
            assert store.delete_memory(9999) is False
            store.close()

    def test_update_heat(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            mem_id = store.insert_memory({"content": "heat test", "heat": 1.0})
            store.update_memory_heat(mem_id, 0.5)
            mem = store.get_memory(mem_id)
            assert mem["heat"] == 0.5
            store.close()

    def test_update_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            mem_id = store.insert_memory({"content": "access test"})
            store.update_memory_access(mem_id)
            mem = store.get_memory(mem_id)
            assert mem["access_count"] == 1
            store.update_memory_access(mem_id)
            mem = store.get_memory(mem_id)
            assert mem["access_count"] == 2
            store.close()

    def test_set_protected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            mem_id = store.insert_memory({"content": "protect me"})
            store.set_memory_protected(mem_id, True)
            mem = store.get_memory(mem_id)
            assert mem["is_protected"] == 1
            store.close()


class TestMemoryQueries:
    def test_get_memories_for_domain(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            store.insert_memory({"content": "dom A", "domain": "alpha", "heat": 0.8})
            store.insert_memory({"content": "dom B", "domain": "beta", "heat": 0.9})
            store.insert_memory({"content": "dom A2", "domain": "alpha", "heat": 0.7})
            results = store.get_memories_for_domain("alpha")
            assert len(results) == 2
            assert all(m["domain"] == "alpha" for m in results)
            store.close()

    def test_get_hot_memories(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            store.insert_memory({"content": "hot", "heat": 0.9})
            store.insert_memory({"content": "cold", "heat": 0.1})
            store.insert_memory({"content": "warm", "heat": 0.8})
            results = store.get_hot_memories(min_heat=0.7)
            assert len(results) == 2
            store.close()

    def test_count_memories(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            store.insert_memory({"content": "a", "store_type": "episodic"})
            store.insert_memory({"content": "b", "store_type": "semantic"})
            counts = store.count_memories()
            assert counts["total"] == 2
            assert counts["episodic"] == 1
            assert counts["semantic"] == 1
            store.close()

    def test_avg_heat(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            store.insert_memory({"content": "a", "heat": 0.8})
            store.insert_memory({"content": "b", "heat": 0.2})
            avg = store.get_avg_heat()
            assert abs(avg - 0.5) < 1e-9
            store.close()


class TestFTS5Search:
    def test_basic_fts_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            store.insert_memory({"content": "Python machine learning tutorial"})
            store.insert_memory({"content": "JavaScript React framework"})
            results = store.search_fts("Python")
            assert len(results) >= 1
            assert results[0][0] == 1  # first memory's rowid
            store.close()

    def test_no_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            store.insert_memory({"content": "hello world"})
            results = store.search_fts("nonexistent_unique_xyz")
            assert len(results) == 0
            store.close()


class TestProspectiveMemory:
    def test_insert_and_get_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            pm_id = store.insert_prospective_memory(
                {
                    "content": "Remember to fix the parser",
                    "trigger_condition": "parser fix",
                    "trigger_type": "keyword_match",
                }
            )
            assert pm_id > 0
            active = store.get_active_prospective_memories()
            assert len(active) == 1
            assert active[0]["content"] == "Remember to fix the parser"
            store.close()

    def test_trigger_and_deactivate(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            pm_id = store.insert_prospective_memory(
                {
                    "content": "task",
                    "trigger_condition": "cond",
                    "trigger_type": "keyword_match",
                }
            )
            store.trigger_prospective_memory(pm_id)
            store.deactivate_prospective_memory(pm_id)
            active = store.get_active_prospective_memories()
            assert len(active) == 0
            store.close()

    def test_count_active_triggers(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            store.insert_prospective_memory(
                {
                    "content": "a",
                    "trigger_condition": "x",
                    "trigger_type": "keyword_match",
                }
            )
            store.insert_prospective_memory(
                {
                    "content": "b",
                    "trigger_condition": "y",
                    "trigger_type": "keyword_match",
                }
            )
            assert store.count_active_triggers() == 2
            store.close()


class TestCheckpoints:
    def test_insert_and_get(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
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
            assert cp["files_being_edited"] == ["test.py"]
            store.close()

    def test_new_checkpoint_deactivates_old(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            store.insert_checkpoint({"current_task": "task 1"})
            store.insert_checkpoint({"current_task": "task 2"})
            cp = store.get_active_checkpoint()
            assert cp["current_task"] == "task 2"
            store.close()

    def test_epoch_tracking(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            assert store.get_current_epoch() == 0
            store.insert_checkpoint({"epoch": 1})
            assert store.get_current_epoch() == 1
            store.close()


class TestEntities:
    def test_insert_and_get(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            eid = store.insert_entity(
                {"name": "PostgreSQL", "type": "technology", "domain": "db"}
            )
            assert eid > 0
            entity = store.get_entity_by_name("PostgreSQL")
            assert entity is not None
            assert entity["type"] == "technology"
            store.close()

    def test_count_entities(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            store.insert_entity({"name": "A", "type": "t"})
            store.insert_entity({"name": "B", "type": "t"})
            assert store.count_entities() == 2
            store.close()


class TestRelationships:
    def test_insert_and_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            e1 = store.insert_entity({"name": "A", "type": "t"})
            e2 = store.insert_entity({"name": "B", "type": "t"})
            rid = store.insert_relationship(
                {
                    "source_entity_id": e1,
                    "target_entity_id": e2,
                    "relationship_type": "uses",
                }
            )
            assert rid > 0
            assert store.count_relationships() == 1
            store.close()


class TestEngramSlots:
    def test_init_and_get_slots(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            store.init_engram_slots(5)
            slots = store.get_all_engram_slots()
            assert len(slots) == 5
            assert all(s["excitability"] == 0.5 for s in slots)
            store.close()

    def test_idempotent_init(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            store.init_engram_slots(5)
            store.init_engram_slots(5)  # Should not duplicate
            assert len(store.get_all_engram_slots()) == 5
            store.close()

    def test_update_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            store.init_engram_slots(3)
            store.update_engram_slot(
                1, excitability=0.9, last_activated="2024-01-01T00:00:00Z"
            )
            slot = store.get_engram_slot(1)
            assert slot["excitability"] == 0.9
            store.close()

    def test_assign_memory_to_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            store.init_engram_slots(3)
            mem_id = store.insert_memory({"content": "slotted"})
            store.assign_memory_slot(mem_id, 2)
            mems = store.get_memories_in_slot(2)
            assert len(mems) == 1
            assert mems[0]["content"] == "slotted"
            store.close()


class TestConsolidationLog:
    def test_log_and_retrieve_last(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            store.log_consolidation({"memories_added": 5, "duration_ms": 100})
            last = store.get_last_consolidation()
            assert last is not None
            store.close()

    def test_no_consolidation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            assert store.get_last_consolidation() is None
            store.close()


class TestArchive:
    def test_insert_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
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
            store.close()
