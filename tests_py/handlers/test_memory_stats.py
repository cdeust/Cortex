"""Tests for mcp_server.handlers.memory_stats — diagnostics handler."""

import asyncio
import tempfile
import os
from unittest.mock import patch

from mcp_server.handlers.memory_stats import handler


def _patch_memory_env(tmp_dir: str):
    db_path = os.path.join(tmp_dir, "test.db")
    return patch.dict(os.environ, {"JARVIS_MEMORY_DB_PATH": db_path})


def _reset_singletons():
    import mcp_server.handlers.memory_stats as mod

    mod._store = None
    from mcp_server.infrastructure.memory_config import get_memory_settings

    get_memory_settings.cache_clear()


class TestMemoryStatsHandler:
    def test_empty_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_memory_env(tmp):
                _reset_singletons()
                result = asyncio.run(handler())
                assert result["total_memories"] == 0
                assert result["avg_heat"] == 0.0
                assert result["total_entities"] == 0
                assert result["total_relationships"] == 0
                assert result["active_triggers"] == 0
                assert result["last_consolidation"] is None
                assert isinstance(result["has_vector_search"], bool)
                _reset_singletons()

    def test_with_stored_memories(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_memory_env(tmp):
                _reset_singletons()
                # Store some memories directly via store
                from mcp_server.infrastructure.memory_store import MemoryStore

                db_path = os.path.join(tmp, "test.db")
                store = MemoryStore(db_path)
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
                _reset_singletons()

    def test_response_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_memory_env(tmp):
                _reset_singletons()
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
                _reset_singletons()
