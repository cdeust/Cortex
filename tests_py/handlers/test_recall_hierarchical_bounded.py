"""ADR-0045 R3 — recall_hierarchical requires a bounded candidate set.

The previous implementation fell back to ``get_all_memories_for_decay()``
when no domain was supplied, then ran agglomerative clustering on the
entire store. Clustering is O(N^2); darval's 66K-memory store OOM'd on
the first no-domain call (field report issue #14).

v3.13.0 removes the fallback: the handler now requires EITHER ``domain``
OR an explicit ``memory_ids`` subset, and raises ``ValidationError`` if
both are missing. This is a **contract change**, not a runtime cap — the
correctness argument is that ``build_hierarchy`` is never called over an
unbounded candidate set.
"""

from __future__ import annotations

import asyncio

import pytest

from mcp_server.errors import ValidationError
from mcp_server.handlers import recall_hierarchical


def test_domain_scoped_call_works():
    """Passing a domain returns a normal (possibly empty) result shape."""
    result = asyncio.run(
        recall_hierarchical.handler({"query": "unit test query", "domain": "cortex"})
    )
    # Postcondition: the handler does not raise; it returns the documented shape.
    assert isinstance(result, dict)
    assert "results" in result
    assert "total" in result
    # With a clean test DB the domain will usually have no memories -> empty.
    assert isinstance(result["results"], list)


def test_memory_ids_scoped_call_works():
    """Passing memory_ids returns the documented shape without raising.

    Seed one memory, pass its id as a 1-element scope list — the
    hierarchy is trivially buildable, but the correctness point is that
    no unbounded scan happens.
    """
    from mcp_server.handlers import remember

    seed = asyncio.run(
        remember.handler(
            {"content": "F1 bounded hierarchy seed memory", "tags": ["f1-test"]}
        )
    )
    if not seed.get("stored"):
        pytest.skip(
            "remember handler rejected the seed; cannot exercise memory_ids path"
        )
    mid = seed["memory_id"]

    result = asyncio.run(
        recall_hierarchical.handler(
            {"query": "bounded hierarchy test", "memory_ids": [mid]}
        )
    )
    assert isinstance(result, dict)
    assert "results" in result
    assert isinstance(result["results"], list)


def test_no_scope_raises_validation_error():
    """No domain, no memory_ids -> ValidationError (contract change)."""
    with pytest.raises(ValidationError) as exc_info:
        asyncio.run(
            recall_hierarchical.handler({"query": "dangerous unscoped query"})
        )

    msg = str(exc_info.value)
    # The message must cite the removal rationale for future readers.
    assert "domain" in msg
    assert "memory_ids" in msg
    assert "O(N" in msg  # references O(N^2) complexity


def test_empty_memory_ids_plus_empty_domain_raises():
    """Empty list memory_ids AND empty domain is the same failure mode."""
    with pytest.raises(ValidationError):
        asyncio.run(
            recall_hierarchical.handler(
                {"query": "q", "domain": "", "memory_ids": []}
            )
        )


def test_missing_query_returns_empty_shape_not_validation_error():
    """Missing query is the pre-existing empty-shape path (not a scope issue)."""
    result = asyncio.run(recall_hierarchical.handler({}))
    assert result == {"results": [], "total": 0, "hierarchy": {}}

    result2 = asyncio.run(recall_hierarchical.handler({"query": ""}))
    assert result2 == {"results": [], "total": 0, "hierarchy": {}}
