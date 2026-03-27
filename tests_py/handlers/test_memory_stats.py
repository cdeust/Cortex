"""Tests for mcp_server.handlers.memory_stats — diagnostics handler."""

import asyncio

from mcp_server.handlers.memory_stats import handler


class TestMemoryStatsHandler:
    def test_empty_store(self):
        result = asyncio.run(handler())
        assert result["total_memories"] == 0
        assert result["avg_heat"] == 0.0
        assert result["total_entities"] == 0
        assert result["total_relationships"] == 0
        assert result["active_triggers"] == 0
        assert result["last_consolidation"] is None
        assert isinstance(result["has_vector_search"], bool)

    def test_with_stored_memories(self):
        from mcp_server.infrastructure.memory_store import MemoryStore

        store = MemoryStore()
        store.insert_memory(
            {"content": "a", "store_type": "episodic", "heat": 0.8}
        )
        store.insert_memory(
            {"content": "b", "store_type": "semantic", "heat": 0.4}
        )
        store.insert_entity({"name": "X", "type": "t"})
        store.insert_prospective_memory(
            {
                "content": "remind",
                "trigger_condition": "c",
                "trigger_type": "keyword_match",
            }
        )
        store.close()

        result = asyncio.run(handler())
        assert result["total_memories"] == 2
        assert result["episodic_count"] == 1
        assert result["semantic_count"] == 1
        assert result["total_entities"] == 1
        assert result["active_triggers"] == 1
        assert result["avg_heat"] > 0

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
