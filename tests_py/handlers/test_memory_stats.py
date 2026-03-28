"""Tests for mcp_server.handlers.memory_stats — diagnostics handler."""

import asyncio

from mcp_server.handlers.memory_stats import handler, _get_store


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
        }
        assert set(result.keys()) == expected_keys
