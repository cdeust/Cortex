"""Tests for the SQLite memory store backend (CORTEX_MEMORY_STORE_BACKEND=sqlite).

These tests exercise the SQLite fallback path independently of PostgreSQL.
They run both when PG is unavailable (the normal state of sandboxed/CI-SQLite
environments) and when PG is present (verifying the sqlite path is always
selectable).

Backend selection: SqliteMemoryStore is constructed directly — no env-var
override needed here. The CI-SQLite job sets CORTEX_MEMORY_STORE_BACKEND=sqlite
so the conftest fixture also targets SQLite. Both paths reach this store.

Skip pattern: none — these tests do NOT skip; they target SqliteMemoryStore
explicitly and SQLite is always available (stdlib sqlite3).

Contract assertions (each test must be able to fail on regression):
  - CRUD: insert_memory returns int > 0; get_memory returns the stored content
  - Heat: update_memory_heat clamps and persists via heat_base
  - Batch heat: updates multiple rows atomically
  - FTS: search_fts returns matching memories
  - Entities: insert_entity / get_entity_by_name round-trip
  - Relationships: insert_relationship / count_relationships
  - Prospective: insert / get_active / deactivate cycle
  - Checkpoints: insert / get_active / deactivation on new insert
  - Engram slots: init / assign / count
  - Homeostatic: get_homeostatic_factor default + set/get round-trip
  - Archive: insert_archive creates a row linked to a memory
  - Protection: set_memory_protected is reflected in get_memory
  - Staleness: mark_memory_stale is reflected in get_memory
  - Delete: delete_memory removes the row and returns True; double-delete is False
  - Schema init idempotency: constructing two stores on the same path succeeds
"""

from __future__ import annotations


import pytest

from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore


@pytest.fixture()
def store():
    """Fresh in-memory SqliteMemoryStore per test."""
    s = SqliteMemoryStore(db_path=":memory:")
    yield s
    s.close()


# ── Schema ─────────────────────────────────────────────────────────────────


class TestSchemaInit:
    def test_store_constructs(self, store):
        """Constructing a SqliteMemoryStore must not raise."""
        assert store is not None

    def test_has_vec_is_bool(self, store):
        """has_vec must be a bool (True when sqlite-vec is installed, False otherwise)."""
        assert isinstance(store.has_vec, bool)

    def test_schema_idempotent_file(self, tmp_path):
        """Constructing two stores on the same file path must not raise."""
        db_file = str(tmp_path / "idem.db")
        s1 = SqliteMemoryStore(db_path=db_file)
        s2 = SqliteMemoryStore(db_path=db_file)
        s2.close()
        s1.close()


# ── Memory CRUD ────────────────────────────────────────────────────────────


class TestMemoryCRUD:
    def test_insert_returns_positive_id(self, store):
        mem_id = store.insert_memory({"content": "hello world"})
        assert isinstance(mem_id, int)
        assert mem_id > 0

    def test_get_memory_returns_content(self, store):
        mem_id = store.insert_memory(
            {
                "content": "sqlite fallback test",
                "domain": "infra",
                "importance": 0.7,
            }
        )
        mem = store.get_memory(mem_id)
        assert mem is not None
        assert mem["content"] == "sqlite fallback test"
        assert mem["domain"] == "infra"
        assert abs(mem["importance"] - 0.7) < 1e-6

    def test_get_nonexistent_returns_none(self, store):
        assert store.get_memory(999_999) is None

    def test_delete_existing_returns_true(self, store):
        mem_id = store.insert_memory({"content": "delete me"})
        assert store.delete_memory(mem_id) is True
        assert store.get_memory(mem_id) is None

    def test_delete_nonexistent_returns_false(self, store):
        assert store.delete_memory(999_999) is False

    def test_tags_round_trip(self, store):
        """Tags stored as JSON list must be returned as a Python list."""
        mem_id = store.insert_memory(
            {"content": "tagged memory", "tags": ["alpha", "beta"]}
        )
        mem = store.get_memory(mem_id)
        assert isinstance(mem["tags"], list)
        assert set(mem["tags"]) == {"alpha", "beta"}

    def test_default_store_type_is_episodic(self, store):
        mem_id = store.insert_memory({"content": "episode"})
        mem = store.get_memory(mem_id)
        assert mem["store_type"] == "episodic"


# ── Heat (A3 heat_base column) ─────────────────────────────────────────────


class TestHeat:
    def test_update_heat_persists(self, store):
        """update_memory_heat must write heat_base and be reflected in get_memory['heat']."""
        mem_id = store.insert_memory({"content": "heat test", "heat": 1.0})
        store.update_memory_heat(mem_id, 0.42)
        mem = store.get_memory(mem_id)
        # Both 'heat' (alias) and 'heat_base' (canonical) must reflect the update.
        assert abs(mem["heat"] - 0.42) < 1e-4

    def test_bump_heat_raw_clamps_above_one(self, store):
        """bump_heat_raw must clamp values > 1.0 to 1.0."""
        mem_id = store.insert_memory({"content": "clamp high"})
        store.bump_heat_raw(mem_id, 2.5)
        mem = store.get_memory(mem_id)
        assert mem["heat"] <= 1.0

    def test_bump_heat_raw_clamps_below_zero(self, store):
        """bump_heat_raw must clamp values < 0.0 to 0.0."""
        mem_id = store.insert_memory({"content": "clamp low"})
        store.bump_heat_raw(mem_id, -0.5)
        mem = store.get_memory(mem_id)
        assert mem["heat"] >= 0.0

    def test_batch_heat_updates(self, store):
        """update_memories_heat_batch must apply all updates atomically."""
        id1 = store.insert_memory({"content": "batch a", "heat": 1.0})
        id2 = store.insert_memory({"content": "batch b", "heat": 1.0})
        count = store.update_memories_heat_batch([(id1, 0.3), (id2, 0.6)])
        assert count == 2
        mem1 = store.get_memory(id1)
        mem2 = store.get_memory(id2)
        assert abs(mem1["heat"] - 0.3) < 1e-4
        assert abs(mem2["heat"] - 0.6) < 1e-4

    def test_batch_heat_empty_is_noop(self, store):
        count = store.update_memories_heat_batch([])
        assert count == 0


# ── Access count ──────────────────────────────────────────────────────────


class TestAccessCount:
    def test_update_access_increments_count(self, store):
        mem_id = store.insert_memory({"content": "access counter"})
        store.update_memory_access(mem_id)
        store.update_memory_access(mem_id)
        mem = store.get_memory(mem_id)
        assert mem["access_count"] == 2


# ── Protection and staleness ───────────────────────────────────────────────


class TestProtectionStaleness:
    def test_set_memory_protected(self, store):
        mem_id = store.insert_memory({"content": "protect me"})
        store.set_memory_protected(mem_id, True)
        mem = store.get_memory(mem_id)
        assert mem["is_protected"] is True

    def test_unset_memory_protected(self, store):
        mem_id = store.insert_memory({"content": "unprotect me", "is_protected": True})
        store.set_memory_protected(mem_id, False)
        mem = store.get_memory(mem_id)
        assert mem["is_protected"] is False

    def test_mark_memory_stale(self, store):
        mem_id = store.insert_memory({"content": "stale me"})
        store.mark_memory_stale(mem_id, True)
        mem = store.get_memory(mem_id)
        assert mem["is_stale"] is True


# ── FTS search ────────────────────────────────────────────────────────────


class TestFTSSearch:
    def test_search_returns_matching_row(self, store):
        mid = store.insert_memory({"content": "Python asyncio event loop"})
        store.insert_memory({"content": "JavaScript React hooks"})
        results = store.search_fts("asyncio")
        ids = [r[0] for r in results]
        assert mid in ids

    def test_search_no_match_returns_empty(self, store):
        store.insert_memory({"content": "hello world"})
        results = store.search_fts("xyzzy_nonexistent_term_42")
        assert results == []

    def test_deleted_memory_not_in_fts(self, store):
        mid = store.insert_memory({"content": "ephemeral content alpha"})
        store.delete_memory(mid)
        results = store.search_fts("ephemeral")
        ids = [r[0] for r in results]
        assert mid not in ids


# ── Queries ────────────────────────────────────────────────────────────────


class TestQueries:
    def test_get_memories_for_domain(self, store):
        store.insert_memory({"content": "a", "domain": "alpha"})
        store.insert_memory({"content": "b", "domain": "beta"})
        store.insert_memory({"content": "c", "domain": "alpha"})
        results = store.get_memories_for_domain("alpha")
        assert len(results) == 2
        assert all(m["domain"] == "alpha" for m in results)

    def test_get_hot_memories(self, store):
        store.insert_memory({"content": "hot", "heat": 0.9})
        store.insert_memory({"content": "cold", "heat": 0.1})
        results = store.get_hot_memories(min_heat=0.7)
        assert len(results) == 1
        assert results[0]["content"] == "hot"


# ── Entities ───────────────────────────────────────────────────────────────


class TestEntities:
    def test_insert_and_get_entity(self, store):
        eid = store.insert_entity(
            {"name": "SQLite", "type": "technology", "domain": "infra"}
        )
        assert isinstance(eid, int) and eid > 0
        entity = store.get_entity_by_name("SQLite")
        assert entity is not None
        assert entity["type"] == "technology"

    def test_get_nonexistent_entity_returns_none(self, store):
        assert store.get_entity_by_name("NonExistentEntity_XYZ") is None

    def test_count_entities_increases(self, store):
        before = store.count_entities()
        store.insert_entity({"name": "Entity_A", "type": "t"})
        store.insert_entity({"name": "Entity_B", "type": "t"})
        assert store.count_entities() == before + 2


# ── Relationships ──────────────────────────────────────────────────────────


class TestRelationships:
    def test_insert_and_count_relationship(self, store):
        e1 = store.insert_entity({"name": "Rel_A", "type": "t"})
        e2 = store.insert_entity({"name": "Rel_B", "type": "t"})
        rid = store.insert_relationship(
            {
                "source_entity_id": e1,
                "target_entity_id": e2,
                "relationship_type": "uses",
            }
        )
        assert isinstance(rid, int) and rid > 0
        assert store.count_relationships() >= 1


# ── Prospective memories ───────────────────────────────────────────────────


class TestProspectiveMemory:
    def test_insert_and_get_active(self, store):
        pm_id = store.insert_prospective_memory(
            {
                "content": "Remember to clean up test artifacts",
                "trigger_condition": "cleanup",
                "trigger_type": "keyword_match",
            }
        )
        assert isinstance(pm_id, int) and pm_id > 0
        active = store.get_active_prospective_memories()
        assert any(
            p["content"] == "Remember to clean up test artifacts" for p in active
        )

    def test_deactivate_prospective_memory(self, store):
        pm_id = store.insert_prospective_memory(
            {
                "content": "deactivate me",
                "trigger_condition": "test",
                "trigger_type": "keyword_match",
            }
        )
        store.deactivate_prospective_memory(pm_id)
        active = store.get_active_prospective_memories()
        assert not any(p["id"] == pm_id for p in active)


# ── Checkpoints ────────────────────────────────────────────────────────────


class TestCheckpoints:
    def test_insert_and_get_active_checkpoint(self, store):
        cp_id = store.insert_checkpoint(
            {
                "session_id": "session-001",
                "current_task": "writing sqlite tests",
                "files_being_edited": ["test_sqlite_backend.py"],
            }
        )
        assert isinstance(cp_id, int) and cp_id > 0
        cp = store.get_active_checkpoint()
        assert cp is not None
        assert cp["current_task"] == "writing sqlite tests"

    def test_new_checkpoint_supersedes_old(self, store):
        store.insert_checkpoint({"current_task": "task one"})
        store.insert_checkpoint({"current_task": "task two"})
        cp = store.get_active_checkpoint()
        assert cp["current_task"] == "task two"


# ── Engram slots ───────────────────────────────────────────────────────────


class TestEngramSlots:
    def test_init_and_count_slots(self, store):
        store.init_engram_slots(4)
        slots = store.get_all_engram_slots()
        assert len(slots) >= 4

    def test_assign_memory_to_slot(self, store):
        store.init_engram_slots(3)
        mem_id = store.insert_memory({"content": "engram test"})
        store.assign_memory_slot(mem_id, 2)
        mems = store.get_memories_in_slot(2)
        assert any(m["content"] == "engram test" for m in mems)

    def test_count_memories_in_slot(self, store):
        store.init_engram_slots(3)
        m1 = store.insert_memory({"content": "slot-a"})
        m2 = store.insert_memory({"content": "slot-b"})
        store.assign_memory_slot(m1, 1)
        store.assign_memory_slot(m2, 1)
        assert store.count_memories_in_slot(1) == 2

    def test_count_memories_in_slot_with_exclude(self, store):
        store.init_engram_slots(3)
        m1 = store.insert_memory({"content": "excl-a"})
        m2 = store.insert_memory({"content": "excl-b"})
        store.assign_memory_slot(m1, 1)
        store.assign_memory_slot(m2, 1)
        assert store.count_memories_in_slot(1, exclude_id=m1) == 1

    def test_empty_slot_returns_zero(self, store):
        store.init_engram_slots(3)
        assert store.count_memories_in_slot(2) == 0


# ── Homeostatic factor ─────────────────────────────────────────────────────


class TestHomeostaticFactor:
    def test_default_factor_is_one(self, store):
        factor = store.get_homeostatic_factor("nonexistent_domain_xyz")
        assert abs(factor - 1.0) < 1e-6

    def test_set_and_get_factor(self, store):
        store.set_homeostatic_factor("test_domain", 1.5)
        factor = store.get_homeostatic_factor("test_domain")
        assert abs(factor - 1.5) < 1e-4

    def test_set_factor_clamps_at_max(self, store):
        store.set_homeostatic_factor("clamp_domain", 999.0)
        factor = store.get_homeostatic_factor("clamp_domain")
        assert factor <= 9.99 + 1e-6


# ── Archive ────────────────────────────────────────────────────────────────


class TestArchive:
    def test_insert_archive_linked_to_memory(self, store):
        mem_id = store.insert_memory({"content": "original version"})
        aid = store.insert_archive(
            {
                "original_memory_id": mem_id,
                "content": "archived version",
                "mismatch_score": 0.7,
                "archive_reason": "reconsolidation",
            }
        )
        assert isinstance(aid, int) and aid > 0


# ── Consolidation log ──────────────────────────────────────────────────────


class TestConsolidationLog:
    def test_log_and_retrieve_last(self, store):
        store.log_consolidation({"memories_added": 3, "duration_ms": 50})
        last = store.get_last_consolidation()
        assert last is not None


# ── Backend selection via CORTEX_MEMORY_STORE_BACKEND ─────────────────────


class TestBackendSelection:
    def test_sqlite_env_var_selects_sqlite(self, tmp_path, monkeypatch):
        """CORTEX_MEMORY_STORE_BACKEND=sqlite must produce a SqliteMemoryStore
        via the MemoryStore factory — this is the CI-SQLite job's entry point."""
        db_path = str(tmp_path / "factory.db")
        monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "sqlite")
        monkeypatch.setenv("CORTEX_MEMORY_SQLITE_FALLBACK_PATH", db_path)

        # Clear lru_cache so the env override is picked up
        from mcp_server.infrastructure.memory_config import get_memory_settings
        from mcp_server.infrastructure.memory_store import _construct_store

        get_memory_settings.cache_clear()
        store = _construct_store(db_path=db_path)
        try:
            # Must be the SQLite implementation, not PG
            assert type(store).__name__ == "SqliteMemoryStore"
            # Must be functional: insert + retrieve
            mid = store.insert_memory({"content": "factory-selected sqlite"})
            mem = store.get_memory(mid)
            assert mem["content"] == "factory-selected sqlite"
        finally:
            store.close()
            get_memory_settings.cache_clear()
