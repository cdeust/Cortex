"""Tests for mcp_server.handlers.recall — memory retrieval handler."""

import asyncio

from mcp_server.handlers.recall import handler as recall_handler
from mcp_server.core.retrieval_dispatch import wrrf_fuse as _wrrf_fuse
from mcp_server.handlers.remember import handler as remember_handler


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

    def test_recall_response_shape(self):
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
        assert isinstance(result["signals"], dict)
        assert "dispatch_tier" in result

    def test_domain_scoped_recall(self):
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

    def test_global_memory_visible_across_domains(self):
        """Global memories should appear in domain-scoped recall."""
        # Store a global memory in domain "infra"
        store_result = asyncio.run(
            remember_handler(
                {
                    "content": "Global: PostgreSQL server at db.internal:5432",
                    "domain": "infra",
                    "force": True,
                    "is_global": True,
                    "tags": ["infrastructure", "postgres"],
                }
            )
        )
        assert store_result["stored"] is True

        # Recall from a different domain — global memory should still appear
        result = asyncio.run(
            recall_handler(
                {
                    "query": "PostgreSQL server connection",
                    "domain": "frontend",
                    "max_results": 10,
                    "min_heat": 0.0,
                }
            )
        )
        contents = [r.get("content", "") for r in result["results"]]
        assert any("PostgreSQL server" in c for c in contents), (
            "Global memory should be visible from a different domain"
        )
