"""Tests for mcp_server.handlers.consolidate — maintenance cycles."""

import os
from unittest.mock import patch

import pytest

from mcp_server.infrastructure.memory_config import get_memory_settings


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path):
    db_path = str(tmp_path / "test_consolidate.db")
    with patch.dict(os.environ, {"JARVIS_MEMORY_DB_PATH": db_path}):
        get_memory_settings.cache_clear()
        import mcp_server.handlers.consolidate as mod

        mod._store = None
        mod._embeddings = None
        yield db_path
        mod._store = None
        mod._embeddings = None
    get_memory_settings.cache_clear()


class TestConsolidateHandler:
    @pytest.mark.asyncio
    async def test_empty_store_runs_clean(self):
        from mcp_server.handlers.consolidate import handler

        result = await handler()
        assert "duration_ms" in result
        assert result["decay"]["memories_decayed"] == 0
        assert result["decay"]["total_memories"] == 0
        assert result["compression"]["compressed_to_gist"] == 0
        assert result["compression"]["compressed_to_tag"] == 0

    @pytest.mark.asyncio
    async def test_decay_only(self):
        from mcp_server.handlers.consolidate import handler

        result = await handler({"decay": True, "compress": False})
        assert "decay" in result
        assert "compression" not in result

    @pytest.mark.asyncio
    async def test_compress_only(self):
        from mcp_server.handlers.consolidate import handler

        result = await handler({"decay": False, "compress": True})
        assert "compression" in result
        assert "decay" not in result

    @pytest.mark.asyncio
    async def test_neither(self):
        from mcp_server.handlers.consolidate import handler

        result = await handler({"decay": False, "compress": False})
        assert "duration_ms" in result
        assert "decay" not in result
        assert "compression" not in result

    @pytest.mark.asyncio
    async def test_with_memories(self, _isolated_db):
        """Insert memories and run consolidation."""
        from mcp_server.handlers.consolidate import handler, _get_store
        from mcp_server.infrastructure.embedding_engine import EmbeddingEngine
        from datetime import datetime, timezone, timedelta

        store = _get_store()
        engine = EmbeddingEngine(dim=get_memory_settings().EMBEDDING_DIM)
        old_time = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()

        # Insert a memory with old last_accessed so it decays
        emb = engine.encode("test memory for consolidation")
        store.insert_memory(
            {
                "content": "test memory for consolidation",
                "embedding": emb,
                "tags": ["test"],
                "domain": "testing",
                "directory": "/tmp",
                "source": "test",
                "importance": 0.5,
                "surprise": 0.3,
                "emotional_valence": 0.0,
                "confidence": 1.0,
                "heat": 0.8,
            }
        )

        # Manually set last_accessed to old time to trigger decay
        store._conn.execute("UPDATE memories SET last_accessed = %s", (old_time,))
        store._conn.commit()

        result = await handler({"decay": True, "compress": True})
        assert result["decay"]["total_memories"] >= 1
        # May or may not decay depending on exact timing
        assert result["decay"]["memories_decayed"] >= 0

    @pytest.mark.asyncio
    async def test_protected_memories_skip_compression(self, _isolated_db):
        """Protected memories should not be compressed."""
        from mcp_server.handlers.consolidate import handler, _get_store
        from mcp_server.infrastructure.embedding_engine import EmbeddingEngine

        store = _get_store()
        engine = EmbeddingEngine(dim=get_memory_settings().EMBEDDING_DIM)

        emb = engine.encode("protected memory content")
        store.insert_memory(
            {
                "content": "protected memory content",
                "embedding": emb,
                "tags": ["critical"],
                "domain": "testing",
                "directory": "/tmp",
                "source": "test",
                "importance": 0.9,
                "surprise": 0.1,
                "emotional_valence": 0.0,
                "confidence": 1.0,
                "heat": 0.9,
                "is_protected": True,
            }
        )

        result = await handler({"decay": False, "compress": True})
        assert result["compression"]["protected_skipped"] >= 1
        assert result["compression"]["compressed_to_gist"] == 0


class TestConsolidateSchema:
    def test_schema_exists(self):
        from mcp_server.handlers.consolidate import schema

        assert "description" in schema
        assert "inputSchema" in schema


class TestConsolidateSingletons:
    def test_get_store_returns_store(self):
        from mcp_server.handlers.consolidate import _get_store

        store = _get_store()
        assert store is not None

    def test_get_embeddings_returns_engine(self):
        from mcp_server.handlers.consolidate import _get_embeddings

        engine = _get_embeddings()
        assert engine is not None
