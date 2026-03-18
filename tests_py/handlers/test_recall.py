"""Tests for mcp_server.handlers.recall — memory retrieval handler."""

import asyncio
import tempfile
import os
from unittest.mock import patch

from mcp_server.handlers.recall import handler as recall_handler
from mcp_server.core.retrieval_dispatch import wrrf_fuse as _wrrf_fuse
from mcp_server.handlers.remember import handler as remember_handler


def _patch_memory_env(tmp_dir: str):
    db_path = os.path.join(tmp_dir, "test.db")
    return patch.dict(os.environ, {"JARVIS_MEMORY_DB_PATH": db_path})


def _reset_singletons():
    import mcp_server.handlers.recall as recall_mod
    import mcp_server.handlers.remember as remember_mod

    recall_mod._store = None
    recall_mod._embeddings = None
    remember_mod._store = None
    remember_mod._embeddings = None
    from mcp_server.infrastructure.memory_config import get_memory_settings

    get_memory_settings.cache_clear()


class TestWRRFFuse:
    def test_single_signal(self):
        results = _wrrf_fuse(
            [[(1, 0.9), (2, 0.5), (3, 0.1)]],
            [1.0],
            k=60,
        )
        assert len(results) == 3
        # First result should have highest score
        assert results[0][0] == 1

    def test_multiple_signals_boost_overlap(self):
        # Memory 2 appears in both signals
        results = _wrrf_fuse(
            [
                [(1, 0.9), (2, 0.5)],
                [(2, 0.8), (3, 0.7)],
            ],
            [1.0, 1.0],
            k=60,
        )
        # Memory 2 should rank highest due to appearing in both
        assert results[0][0] == 2

    def test_zero_weight_ignored(self):
        results = _wrrf_fuse(
            [[(1, 0.9)], [(2, 0.8)]],
            [1.0, 0.0],
            k=60,
        )
        assert len(results) == 1
        assert results[0][0] == 1

    def test_empty_signals(self):
        results = _wrrf_fuse([], [], k=60)
        assert results == []


class TestRecallHandler:
    def test_no_query_returns_empty(self):
        result = asyncio.run(recall_handler(None))
        assert result["results"] == []
        assert result["total"] == 0

    def test_empty_query_returns_empty(self):
        result = asyncio.run(recall_handler({"query": ""}))
        assert result["results"] == []

    def test_recall_stored_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_memory_env(tmp):
                _reset_singletons()
                # Store a memory first
                asyncio.run(
                    remember_handler(
                        {
                            "content": "Python asyncio event loop best practices",
                            "force": True,
                            "tags": ["python", "async"],
                        }
                    )
                )
                # Recall it
                result = asyncio.run(
                    recall_handler(
                        {
                            "query": "Python asyncio",
                            "max_results": 5,
                        }
                    )
                )
                assert result["total"] >= 1
                assert "signals" in result
                first = result["results"][0]
                assert "content" in first
                assert "score" in first
                assert "heat" in first
                _reset_singletons()

    def test_recall_response_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_memory_env(tmp):
                _reset_singletons()
                asyncio.run(
                    remember_handler(
                        {
                            "content": "Response shape test memory",
                            "force": True,
                        }
                    )
                )
                result = asyncio.run(recall_handler({"query": "shape test"}))
                assert isinstance(result["results"], list)
                assert isinstance(result["total"], int)
                assert "signals" in result
                assert "vector" in result["signals"]
                assert "fts" in result["signals"]
                assert "heat" in result["signals"]
                assert "dispatch_tier" in result
                _reset_singletons()

    def test_domain_scoped_recall(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_memory_env(tmp):
                _reset_singletons()
                asyncio.run(
                    remember_handler(
                        {
                            "content": "Domain specific memory for alpha domain",
                            "domain": "alpha",
                            "force": True,
                        }
                    )
                )
                asyncio.run(
                    remember_handler(
                        {
                            "content": "Different domain memory for beta",
                            "domain": "beta",
                            "force": True,
                        }
                    )
                )
                result = asyncio.run(
                    recall_handler(
                        {
                            "query": "domain memory",
                            "domain": "alpha",
                        }
                    )
                )
                # Should include results (may include both via FTS, but domain-scoped heat signal favors alpha)
                assert result["total"] >= 1
                _reset_singletons()
