"""Tests for mcp_server.handlers.navigate_memory — SR co-access BFS traversal.

Contract under test (from handler docstring and schema):
  - No args / missing memory_id  → {"neighbors": [], "total": 0}
  - memory_id not in store       → {"neighbors": [], "total": 0, "reason": "memory_not_found"}
  - Seed exists, no co-access    → {"start_memory_id": int, "neighbors": [], "total": 0,
                                    "sr_graph_size": int, "reason": "no_co_access_neighbors_found"}
  - Seed + neighbors reachable   → {"start_memory_id": int, "start_content": str,
                                    "neighbors": [...], "total": int, "max_depth": int,
                                    "sr_graph_size": int}
  - max_depth hard-capped at 4 regardless of caller input
  - include_2d_map=True with neighbors → result contains "coordinates_2d"
  - neighbors sorted ascending by sr_distance
  - each neighbor carries: memory_id, sr_distance, hops, path, content, heat, domain, tags
"""

from __future__ import annotations

import asyncio


from mcp_server.handlers.navigate_memory import handler as navigate_handler


# ── Helpers ───────────────────────────────────────────────────────────────


def _get_store():
    """Return the navigate_memory handler's own store singleton.

    IMPORTANT: all test helpers MUST use this function so that seeded
    memories and the handler-under-test share exactly one store instance.
    Using remember_handler to seed would initialise a DIFFERENT singleton,
    which is reset by the conftest _test_isolation fixture between calls —
    causing write and handler-call to hit different store instances and
    producing the ~60% flake rate (pattern confirmed by adversarial review).
    """
    from mcp_server.handlers.navigate_memory import _get_store as gs

    return gs()


def _store_memory(content: str, **kwargs) -> int:
    """Insert a memory directly via the handler's own store and return its id.

    Accepts the same field kwargs as insert_memory (domain, tags, source, …).
    The memory starts with access_count=0; callers must call
    store.update_memory_access() when get_recently_accessed_memories
    (min_access_count=1) must return it.
    """
    store = _get_store()
    data = {"content": content, "confidence": 1.0, **kwargs}
    return store.insert_memory(data)


def _store_coaccessed_pair(content_a: str, content_b: str) -> tuple[int, int]:
    """Insert two memories and touch both so they appear in
    get_recently_accessed_memories (access_count >= 1).

    Both memories get the same last_accessed timestamp (within the default
    2-hour window) so build_temporal_co_access creates an edge between them.
    Returns (mid_a, mid_b).

    update_memory_access() MUST succeed for both memories; a silent failure
    would leave access_count=0, preventing get_recently_accessed_memories
    (min_access_count=1) from returning them, so no co-access edge would form
    and navigate_handler would always return no_co_access_neighbors_found
    (non-deterministic ~60% flake, diagnosed 2026-06-17).
    """
    store = _get_store()
    mid_a = _store_memory(content_a)
    mid_b = _store_memory(content_b)
    # Touch both: increments access_count to 1, updates last_accessed.
    # Raises on failure — a swallowed exception here is a non-vacuous
    # test precondition failure, not an ignorable edge case.
    for mid in (mid_a, mid_b):
        store.update_memory_access(mid)
        # Verify the access was recorded (belt-and-suspenders against a silent
        # store that returns success but does not persist).
        mem = store.get_memory(mid)
        assert mem is not None, f"memory {mid} vanished after update_memory_access"
        assert (mem.get("access_count") or 0) >= 1, (
            f"access_count not incremented for memory {mid}: "
            f"got {mem.get('access_count')!r}"
        )
    return mid_a, mid_b


# ── Early-return and missing-memory contracts ─────────────────────────────


class TestNavigateNoArgs:
    """Handler must return the minimal shape when called with no useful input."""

    def test_none_args_returns_empty(self):
        result = asyncio.run(navigate_handler(None))
        assert result["neighbors"] == []
        assert result["total"] == 0

    def test_empty_dict_returns_empty(self):
        result = asyncio.run(navigate_handler({}))
        assert result["neighbors"] == []
        assert result["total"] == 0

    def test_missing_memory_id_key_returns_empty(self):
        result = asyncio.run(navigate_handler({"max_depth": 2}))
        assert result["neighbors"] == []
        assert result["total"] == 0


class TestNavigateMemoryNotFound:
    """A memory_id that does not exist in the store must yield memory_not_found."""

    def test_nonexistent_id_reason(self):
        result = asyncio.run(navigate_handler({"memory_id": 999_999_999}))
        assert result["neighbors"] == []
        assert result["total"] == 0
        assert result.get("reason") == "memory_not_found"

    def test_nonexistent_id_no_start_content(self):
        result = asyncio.run(navigate_handler({"memory_id": 888_888_888}))
        assert "start_content" not in result


# ── Isolated seed (no co-access neighbors) ────────────────────────────────


class TestNavigateIsolatedSeed:
    """A seed that exists but has no co-accessed neighbors returns the empty-graph shape."""

    def test_isolated_seed_reason(self):
        mid = _store_memory("isolated memory with unique content xyz987")
        result = asyncio.run(navigate_handler({"memory_id": mid}))
        assert result.get("reason") == "no_co_access_neighbors_found"

    def test_isolated_seed_shape(self):
        mid = _store_memory("another isolated memory abc123")
        result = asyncio.run(navigate_handler({"memory_id": mid}))
        assert result["start_memory_id"] == mid
        assert result["neighbors"] == []
        assert result["total"] == 0
        assert "sr_graph_size" in result
        assert isinstance(result["sr_graph_size"], int)


# ── Success path (seed + reachable neighbors) ─────────────────────────────


def _assert_neighbors_found(result: dict, context: str) -> None:
    """Assert that the navigation result contains neighbors.

    _store_coaccessed_pair guarantees access_count >= 1 for both memories and
    both timestamps within 2 hours, so build_temporal_co_access WILL create an
    edge.  If navigate_handler still returns no_co_access_neighbors_found,
    the precondition was violated — fail loudly rather than skipping.

    A pytest.skip here is a vacuous pass that hides regressions.
    """
    assert result.get("reason") != "memory_not_found", (
        f"{context}: seed memory not found — store seeding failed "
        "(shared-singleton bug?)"
    )
    assert result.get("reason") != "no_co_access_neighbors_found", (
        f"{context}: no co-access neighbors — _store_coaccessed_pair "
        "precondition not met (access_count < 1 or timestamps outside window?)"
    )
    assert result.get("neighbors"), (
        f"{context}: neighbors list is empty in success result: {result}"
    )


class TestNavigateWithNeighbors:
    """When neighbors exist, the full result shape must be satisfied.

    Every test in this class uses _store_coaccessed_pair which guarantees
    co-access edges exist (access_count >= 1, timestamps within 2h window).
    No pytest.skip is used — a vacuous skip hides regressions.
    """

    def test_success_result_keys(self):
        mid_a, _mid_b = _store_coaccessed_pair(
            "navigate seed memory for SR test alpha",
            "navigate neighbor memory for SR test beta",
        )
        result = asyncio.run(navigate_handler({"memory_id": mid_a}))
        _assert_neighbors_found(result, "test_success_result_keys")
        required = {
            "start_memory_id",
            "start_content",
            "neighbors",
            "total",
            "max_depth",
            "sr_graph_size",
        }
        missing = required - result.keys()
        assert not missing, f"Result missing keys: {missing}"

    def test_success_start_content_matches_stored(self):
        mid_a, _mid_b = _store_coaccessed_pair(
            "navigate seed memory for SR test alpha",
            "navigate neighbor memory for SR test beta",
        )
        result = asyncio.run(navigate_handler({"memory_id": mid_a}))
        _assert_neighbors_found(result, "test_success_start_content_matches_stored")
        assert "navigate seed memory for SR test alpha" in result["start_content"]

    def test_success_total_matches_neighbors_length(self):
        mid_a, _mid_b = _store_coaccessed_pair(
            "navigate seed memory total check seed",
            "navigate neighbor memory total check neighbor",
        )
        result = asyncio.run(navigate_handler({"memory_id": mid_a}))
        _assert_neighbors_found(result, "test_success_total_matches_neighbors_length")
        assert result["total"] == len(result["neighbors"])

    def test_neighbors_sorted_ascending_by_sr_distance(self):
        """Postcondition: _enrich_neighbors sorts by distance ascending."""
        mid_a, _mid_b = _store_coaccessed_pair(
            "sort test seed memory alpha",
            "sort test neighbor memory beta",
        )
        result = asyncio.run(navigate_handler({"memory_id": mid_a}))
        _assert_neighbors_found(
            result, "test_neighbors_sorted_ascending_by_sr_distance"
        )
        distances = [n["sr_distance"] for n in result["neighbors"]]
        assert distances == sorted(distances), (
            "neighbors not sorted by sr_distance ascending"
        )

    def test_each_neighbor_has_required_fields(self):
        """Each neighbor dict must carry the fields the schema promises."""
        mid_a, _mid_b = _store_coaccessed_pair(
            "fields test seed memory alpha",
            "fields test neighbor memory beta",
        )
        result = asyncio.run(navigate_handler({"memory_id": mid_a}))
        _assert_neighbors_found(result, "test_each_neighbor_has_required_fields")
        required_neighbor_fields = {
            "memory_id",
            "sr_distance",
            "hops",
            "path",
            "content",
            "heat",
            "domain",
            "tags",
        }
        for neighbor in result["neighbors"]:
            missing = required_neighbor_fields - neighbor.keys()
            assert not missing, f"Neighbor missing keys: {missing}"

    def test_max_depth_reflected_in_result(self):
        mid_a, _mid_b = _store_coaccessed_pair(
            "depth reflected seed memory",
            "depth reflected neighbor memory",
        )
        result = asyncio.run(navigate_handler({"memory_id": mid_a, "max_depth": 3}))
        _assert_neighbors_found(result, "test_max_depth_reflected_in_result")
        assert result.get("max_depth") == 3


# ── max_depth cap at 4 ────────────────────────────────────────────────────


class TestNavigateMaxDepthCap:
    """max_depth > 4 must be silently capped to 4 (handler invariant).

    The cap is applied in _handler_impl before any SR graph work:
        max_depth = min(int(args.get("max_depth", 2)), 4)
    The cap is visible in the result["max_depth"] field, which is only
    present in the success path.

    Both tests build a guaranteed co-access scenario so that navigate_handler
    returns the SUCCESS shape and the assertion is unconditional.
    _store_coaccessed_pair ensures access_count >= 1 for both memories and
    both last_accessed timestamps land within the 2-hour window, so
    build_temporal_co_access WILL produce an edge and navigate_from WILL
    find at least one neighbor.  A vacuous `return` on "no_co_access_
    neighbors_found" is deliberately absent: if that path fires, the test
    must fail loudly — it means _store_coaccessed_pair broke the invariant.
    """

    def test_depth_capped_at_4_when_caller_passes_10(self):
        """Even if caller passes max_depth=10, result max_depth must be <= 4.

        Unconditional assertion: memory was found AND neighbors exist
        (guaranteed by _store_coaccessed_pair's postcondition).
        """
        mid_a, _mid_b = _store_coaccessed_pair(
            "depth cap test seed memory unique val 77712",
            "depth cap test neighbor memory unique val 77713",
        )
        result = asyncio.run(navigate_handler({"memory_id": mid_a, "max_depth": 10}))
        # Seed must be found — no_memory_not_found is a store-seeding bug.
        assert result.get("reason") != "memory_not_found", (
            "Seed memory not found — store seeding failed (shared-singleton bug?)"
        )
        # Co-access edge must have formed — no_co_access_neighbors_found means
        # _store_coaccessed_pair failed to satisfy access_count >= 1.
        assert result.get("reason") != "no_co_access_neighbors_found", (
            "No co-access neighbors found — _store_coaccessed_pair precondition "
            "not satisfied (access_count < 1 for one or both memories?)"
        )
        # Success path: max_depth key must be present and capped.
        assert "max_depth" in result, (
            f"max_depth key absent in success result: {result}"
        )
        assert result["max_depth"] <= 4, (
            f"max_depth not capped: got {result['max_depth']}, expected <= 4"
        )

    def test_depth_1_accepted(self):
        """max_depth=1 is a valid caller value and must be preserved in the result.

        Unconditional assertion: memory was found AND neighbors exist.
        """
        mid_a, _mid_b = _store_coaccessed_pair(
            "depth 1 test seed memory unique val 88823",
            "depth 1 test neighbor memory unique val 88824",
        )
        result = asyncio.run(navigate_handler({"memory_id": mid_a, "max_depth": 1}))
        assert result.get("reason") != "memory_not_found", (
            "Seed memory not found — store seeding failed (shared-singleton bug?)"
        )
        assert result.get("reason") != "no_co_access_neighbors_found", (
            "No co-access neighbors found — _store_coaccessed_pair precondition "
            "not satisfied (access_count < 1 for one or both memories?)"
        )
        assert "max_depth" in result, (
            f"max_depth key absent in success result: {result}"
        )
        assert result["max_depth"] == 1, (
            f"max_depth=1 not preserved: got {result['max_depth']}"
        )


# ── 2D map flag ───────────────────────────────────────────────────────────


class TestNavigate2DMap:
    """include_2d_map=False must not add coordinates_2d; True adds it when neighbors exist."""

    def test_no_2d_map_by_default(self):
        mid = _store_memory("no 2d map test memory xzx991")
        result = asyncio.run(navigate_handler({"memory_id": mid}))
        assert "coordinates_2d" not in result

    def test_2d_map_absent_without_neighbors(self):
        """include_2d_map=True but no neighbors — coordinates_2d is still absent."""
        mid = _store_memory("2d map empty test memory zqq882")
        result = asyncio.run(
            navigate_handler({"memory_id": mid, "include_2d_map": True})
        )
        # Handler only attaches coordinates_2d when there ARE neighbors
        # (conditional in _handler_impl: `if include_2d and neighbors`)
        assert "coordinates_2d" not in result


# ── Schema presence ───────────────────────────────────────────────────────


class TestNavigateSchema:
    """The schema export must satisfy MCP tool registration requirements."""

    def test_schema_has_required_keys(self):
        from mcp_server.handlers.navigate_memory import schema

        assert "description" in schema
        assert "inputSchema" in schema

    def test_schema_requires_memory_id(self):
        from mcp_server.handlers.navigate_memory import schema

        assert "memory_id" in schema["inputSchema"]["required"]

    def test_schema_properties_cover_all_args(self):
        from mcp_server.handlers.navigate_memory import schema

        props = schema["inputSchema"]["properties"]
        assert "memory_id" in props
        assert "max_depth" in props
        assert "include_2d_map" in props
        assert "window_hours" in props


# ── Singleton accessor ────────────────────────────────────────────────────


class TestNavigateStoreSingleton:
    def test_get_store_returns_non_none(self):
        from mcp_server.handlers.navigate_memory import _get_store

        store = _get_store()
        assert store is not None
