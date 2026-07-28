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
        assert result["memories"] == []
        assert result["count"] == 0

    def test_empty_query_returns_empty(self):
        result = asyncio.run(recall_handler({"query": ""}))
        assert result["memories"] == []

    def test_issue_46_schema_aligned_keys(self):
        """Issue #46: every recall response must satisfy the MCP outputSchema.

        Schema requires: ``memories`` (array). Strictly enforced by Claude
        Code's MCP host, which would otherwise reject the response with
        ``Output validation error: 'memories' is a required property``.

        The legacy ``results``/``total``/``query_intent`` aliases were
        removed 2026-06-10: they byte-duplicated every memory on the wire
        (815KB response for 15 memories, 50% duplication — bounded-I/O audit).
        """
        # Early-return path (no query)
        result = asyncio.run(recall_handler(None))
        assert "memories" in result, "issue #46: schema requires 'memories' key"
        assert "count" in result, "issue #46: schema declares 'count'"
        assert "intent" in result, "issue #46: schema declares 'intent'"
        assert result["memories"] == []
        assert result["count"] == 0
        # Legacy aliases must NOT come back — they double the payload.
        assert "results" not in result and "total" not in result

        # Empty-query path
        result = asyncio.run(recall_handler({"query": ""}))
        assert "memories" in result
        assert result["memories"] == []
        assert "intent" in result

    def test_issue_46_intent_in_schema_enum(self):
        """Issue #46 drift 2: any string the classifier emits must be in
        the schema's intent enum, or MCP validation rejects it. Verify
        the early-return uses an enum-valid value and that the broadened
        enum includes every QueryIntent constant (so the GENERAL fallback
        no longer fails)."""
        from mcp_server.core.query_intent import QueryIntent

        # The schema's broadened enum should include EVERY public string
        # constant on QueryIntent so the classifier can't produce an
        # out-of-enum value.
        schema_enum = {
            "temporal",
            "causal",
            "semantic",
            "entity",
            "knowledge_update",
            "multi_hop",
            "instruction",
            "event_order",
            "summarization",
            "preference",
            "general",
        }
        for attr in dir(QueryIntent):
            if attr.startswith("_") or attr != attr.upper():
                continue
            value = getattr(QueryIntent, attr)
            if isinstance(value, str):
                assert value in schema_enum, (
                    f"QueryIntent.{attr}={value!r} missing from recall "
                    f"outputSchema enum — would fail MCP validation"
                )
        # Early-return uses a schema-valid intent
        result = asyncio.run(recall_handler(None))
        assert result["intent"] in schema_enum

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
        assert result["count"] >= 1
        assert "signals" in result
        first = result["memories"][0]
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
        assert isinstance(result["memories"], list)
        assert isinstance(result["count"], int)
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
        # Should include results (may include both via FTS, but domain-scoped heat
        # signal favors alpha)
        assert result["count"] >= 1

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
        contents = [r.get("content", "") for r in result["memories"]]
        assert any("PostgreSQL server" in c for c in contents), (
            "Global memory should be visible from a different domain"
        )


# ── Issue #17 — handler returns dict, not str ─────────────────────────────


class TestRecallReturnsDict:
    """Liskov: recall handler must return a dict per its output_schema."""

    def test_handler_direct_returns_dict(self):
        import asyncio
        from mcp_server.handlers.recall import handler

        result = asyncio.run(handler(None))
        assert isinstance(result, dict)

    def test_safe_handler_returns_dict(self):
        import asyncio
        from mcp_server.handlers.recall import handler
        from mcp_server.tool_error_handler import safe_handler

        result = asyncio.run(safe_handler(handler, {"query": ""}, tool_name="recall"))
        assert isinstance(result, dict)
        assert not isinstance(result, str)
