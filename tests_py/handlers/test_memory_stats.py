"""Tests for mcp_server.handlers.memory_stats — diagnostics handler."""

import asyncio

from mcp_server.handlers import memory_stats
from mcp_server.handlers.memory_stats import handler, _get_store
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore


class TestMemoryStatsHandler:
    def test_returns_valid_stats(self):
        result = asyncio.run(handler())
        assert isinstance(result["total_memories"], int)
        assert isinstance(result["avg_heat"], (int, float))
        assert isinstance(result["total_entities"], int)
        assert isinstance(result["total_relationships"], int)
        assert isinstance(result["active_triggers"], int)
        assert isinstance(result["has_vector_search"], bool)

    def test_counts_increase_after_insert(self):
        store = _get_store()
        before = asyncio.run(handler())
        initial = before["total_memories"]

        store.insert_memory({"content": "a", "store_type": "episodic", "heat": 0.8})
        store.insert_memory({"content": "b", "store_type": "semantic", "heat": 0.4})
        store._conn.commit()

        after = asyncio.run(handler())
        assert after["total_memories"] == initial + 2
        assert after["avg_heat"] > 0

    def test_response_shape(self):
        result = asyncio.run(handler())
        expected_keys = {
            "total_memories",
            "episodic_count",
            "semantic_count",
            "active_count",
            "archived_count",
            "stale_count",
            "protected_count",
            "avg_heat",
            "total_entities",
            "total_relationships",
            "active_triggers",
            "last_consolidation",
            "has_vector_search",
            "grooming_staleness",
            "grooming_staleness_threshold_days",
        }
        assert set(result.keys()) == expected_keys

    def test_grooming_staleness_shape(self):
        """G-4: staleness is a per-kind dict, ages-only (no backlog
        counts -- those live behind get_grooming_health, not this ~75ms
        health-check tool)."""
        result = asyncio.run(handler())
        staleness = result["grooming_staleness"]
        assert set(staleness.keys()) == {"wiki", "distillation", "promotion"}
        for kind_stats in staleness.values():
            assert set(kind_stats.keys()) == {
                "last_run_at",
                "days_since_last_run",
                "stale",
            }
            assert isinstance(kind_stats["stale"], bool)
        assert result["grooming_staleness_threshold_days"] > 0

    def test_grooming_staleness_never_run_is_stale(self):
        """A kind with no last_run_at (never executed) must be flagged
        stale unconditionally -- undefined age exceeds any threshold."""
        result = asyncio.run(handler())
        for kind_stats in result["grooming_staleness"].values():
            if kind_stats["last_run_at"] is None:
                assert kind_stats["stale"] is True
                assert kind_stats["days_since_last_run"] is None

    def test_works_on_sqlite_backend(self, monkeypatch):
        """Plugin-default backend: memory_stats must not AttributeError.

        Repro: get_grooming_ages existed only on PgStatsMixin, so this
        handler crashed on every SQLite install -- observed on a real
        30k-memory setup run, 2026-07-22."""
        sqlite_store = SqliteMemoryStore(db_path=":memory:")
        monkeypatch.setattr(memory_stats, "_store", sqlite_store)
        try:
            result = asyncio.run(handler())
        finally:
            sqlite_store.close()
        staleness = result["grooming_staleness"]
        assert set(staleness.keys()) == {"wiki", "distillation", "promotion"}
        for kind_stats in staleness.values():
            assert kind_stats["last_run_at"] is None
            assert kind_stats["stale"] is True
