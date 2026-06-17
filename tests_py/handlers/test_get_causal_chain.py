"""Tests for mcp_server.handlers.get_causal_chain — entity-graph BFS traversal.

Contract under test
-------------------
_handler_impl (wrapped as handler) implements these postconditions:

P1. No args → empty result with reason "provide entity_name or memory_id".
P2. entity_name not in store → empty result with reason "entity not found: <name>".
P3. memory_id pointing to unknown memory → empty result with
    reason "no known entities found in memory".
P4. Known entity with relationships → result shape:
    {start_entity: {id, name, type}, chain: [...edges], total_edges, related_memories,
     max_depth, direction}
P5. Depth cap: max_depth argument is honoured (capped at 5 internally).
P6. Relationship type filter: relationship_types filters the edges returned.
P7. Direction filter: direction="outgoing"/"incoming"/"both" is respected.
P8. Schema exists and carries required fields.

The handler uses the shared SQLite store when PG is absent, so all tests run
in both environments via the autouse _test_isolation fixture in conftest.py.
"""

from __future__ import annotations

import asyncio


# ── Helpers ───────────────────────────────────────────────────────────────


def _run(coro):
    """Synchronous wrapper — keeps tests compatible with pytest-asyncio absent."""
    return asyncio.run(coro)


def _get_store():
    from mcp_server.handlers.get_causal_chain import _get_store as gs

    return gs()


def _insert_entity(store, name: str, entity_type: str = "concept") -> int:
    """Insert an entity and return its id."""
    return store.insert_entity({"name": name, "type": entity_type, "domain": "testing"})


def _insert_relationship(
    store, src_id: int, tgt_id: int, rel_type: str = "caused_by"
) -> int:
    return store.insert_relationship(
        {
            "source_entity_id": src_id,
            "target_entity_id": tgt_id,
            "relationship_type": rel_type,
            "weight": 1.0,
            "confidence": 1.0,
            "is_causal": True,
        }
    )


# ── P1 — Missing args ─────────────────────────────────────────────────────


class TestMissingArgs:
    """P1: no entity_name and no memory_id returns empty chain with reason."""

    def test_no_args_returns_empty_chain(self):
        from mcp_server.handlers.get_causal_chain import _handler_impl

        result = _run(_handler_impl(None))
        assert result["chain"] == []
        assert result["total_edges"] == 0
        assert "reason" in result
        assert "provide" in result["reason"].lower()

    def test_empty_args_dict_returns_empty_chain(self):
        from mcp_server.handlers.get_causal_chain import _handler_impl

        result = _run(_handler_impl({}))
        assert result["chain"] == []
        assert result["total_edges"] == 0
        assert "reason" in result


# ── P2 — Entity not found ─────────────────────────────────────────────────


class TestEntityNotFound:
    """P2: entity_name that is not in the store returns empty chain."""

    def test_unknown_entity_name_returns_empty(self):
        from mcp_server.handlers.get_causal_chain import _handler_impl

        result = _run(_handler_impl({"entity_name": "NonExistentEntity_xyz_999"}))
        assert result["chain"] == []
        assert result["total_edges"] == 0
        assert "reason" in result
        assert "NonExistentEntity_xyz_999" in result["reason"]

    def test_reason_includes_entity_name(self):
        from mcp_server.handlers.get_causal_chain import _handler_impl

        result = _run(_handler_impl({"entity_name": "Ghost"}))
        assert "Ghost" in result["reason"]


# ── P3 — Unknown memory_id ────────────────────────────────────────────────


class TestUnknownMemoryId:
    """P3: memory_id for a non-existent memory returns empty chain."""

    def test_unknown_memory_id_returns_empty(self):
        from mcp_server.handlers.get_causal_chain import _handler_impl

        result = _run(_handler_impl({"memory_id": 999999}))
        assert result["chain"] == []
        assert result["total_edges"] == 0
        assert "reason" in result


# ── P4 — Success shape ────────────────────────────────────────────────────


class TestSuccessShape:
    """P4: known entity + relationships → well-formed result."""

    def test_start_entity_shape(self):
        from mcp_server.handlers.get_causal_chain import _handler_impl

        store = _get_store()
        src_id = _insert_entity(store, "DatabaseError", "error")
        tgt_id = _insert_entity(store, "NullPointer", "error")
        _insert_relationship(store, src_id, tgt_id, "caused_by")

        result = _run(_handler_impl({"entity_name": "DatabaseError"}))
        assert "start_entity" in result
        se = result["start_entity"]
        assert se["name"] == "DatabaseError"
        assert "id" in se
        assert "type" in se

    def test_chain_is_list(self):
        from mcp_server.handlers.get_causal_chain import _handler_impl

        store = _get_store()
        src_id = _insert_entity(store, "Alpha", "concept")
        tgt_id = _insert_entity(store, "Beta", "concept")
        _insert_relationship(store, src_id, tgt_id, "depends_on")

        result = _run(_handler_impl({"entity_name": "Alpha"}))
        assert isinstance(result["chain"], list)
        assert result["total_edges"] == len(result["chain"])

    def test_edge_record_fields(self):
        """Each edge must expose: source_id/name/type, target_id/name/type,
        relationship_type, weight, confidence, depth."""
        from mcp_server.handlers.get_causal_chain import _handler_impl

        store = _get_store()
        src_id = _insert_entity(store, "CauseX", "concept")
        tgt_id = _insert_entity(store, "EffectY", "concept")
        _insert_relationship(store, src_id, tgt_id, "caused_by")

        result = _run(_handler_impl({"entity_name": "CauseX"}))
        assert result["total_edges"] >= 1
        edge = result["chain"][0]
        for field in (
            "source_id",
            "source_name",
            "source_type",
            "target_id",
            "target_name",
            "target_type",
            "relationship_type",
            "weight",
            "confidence",
            "depth",
        ):
            assert field in edge, f"edge missing field: {field}"

    def test_total_edges_matches_chain_length(self):
        from mcp_server.handlers.get_causal_chain import _handler_impl

        store = _get_store()
        root_id = _insert_entity(store, "RootNode", "concept")
        for i in range(3):
            child_id = _insert_entity(store, f"Child{i}", "concept")
            _insert_relationship(store, root_id, child_id, "depends_on")

        result = _run(_handler_impl({"entity_name": "RootNode"}))
        assert result["total_edges"] == len(result["chain"])

    def test_related_memories_is_list(self):
        from mcp_server.handlers.get_causal_chain import _handler_impl

        store = _get_store()
        _insert_entity(store, "SomeEntity", "concept")

        result = _run(_handler_impl({"entity_name": "SomeEntity"}))
        # Entity exists but no relationships — result is NOT an empty-chain response
        assert "start_entity" in result
        assert isinstance(result["related_memories"], list)

    def test_max_depth_and_direction_in_result(self):
        from mcp_server.handlers.get_causal_chain import _handler_impl

        store = _get_store()
        src_id = _insert_entity(store, "DepSource", "concept")
        tgt_id = _insert_entity(store, "DepTarget", "concept")
        _insert_relationship(store, src_id, tgt_id, "depends_on")

        result = _run(
            _handler_impl(
                {"entity_name": "DepSource", "max_depth": 2, "direction": "outgoing"}
            )
        )
        assert result["max_depth"] == 2
        assert result["direction"] == "outgoing"


# ── P5 — Depth cap ────────────────────────────────────────────────────────


class TestDepthCap:
    """P5: max_depth is capped at 5 regardless of caller input."""

    def test_max_depth_capped_at_five(self):
        """Handler caps max_depth=10 input to 5."""
        from mcp_server.handlers.get_causal_chain import _handler_impl

        store = _get_store()
        src_id = _insert_entity(store, "CapSrc", "concept")
        tgt_id = _insert_entity(store, "CapTgt", "concept")
        _insert_relationship(store, src_id, tgt_id, "caused_by")

        result = _run(_handler_impl({"entity_name": "CapSrc", "max_depth": 10}))
        # The handler applies min(max_depth, 5); result["max_depth"] must be ≤ 5
        assert result["max_depth"] <= 5

    def test_max_depth_one_limits_traversal(self):
        """max_depth=1 must not return depth-2 edges."""
        from mcp_server.handlers.get_causal_chain import _handler_impl

        store = _get_store()
        a_id = _insert_entity(store, "NodeA", "concept")
        b_id = _insert_entity(store, "NodeB", "concept")
        c_id = _insert_entity(store, "NodeC", "concept")
        _insert_relationship(store, a_id, b_id, "caused_by")
        _insert_relationship(store, b_id, c_id, "caused_by")

        result = _run(_handler_impl({"entity_name": "NodeA", "max_depth": 1}))
        # With depth=1, BFS from NodeA stops after visiting depth=0 neighbours;
        # no depth-2 edges (A→B→C) should appear.
        depths = [e["depth"] for e in result["chain"]]
        assert all(d <= 1 for d in depths), f"Found depth > 1: {depths}"


# ── P6 — Relationship type filter ────────────────────────────────────────


class TestRelationshipFilter:
    """P6: relationship_types filters edges by type."""

    def test_filter_keeps_matching_type(self):
        from mcp_server.handlers.get_causal_chain import _handler_impl

        store = _get_store()
        src_id = _insert_entity(store, "FilterSrc", "concept")
        tgt1_id = _insert_entity(store, "FilterTgt1", "concept")
        tgt2_id = _insert_entity(store, "FilterTgt2", "concept")
        _insert_relationship(store, src_id, tgt1_id, "caused_by")
        _insert_relationship(store, src_id, tgt2_id, "imports")

        result = _run(
            _handler_impl(
                {
                    "entity_name": "FilterSrc",
                    "relationship_types": ["caused_by"],
                }
            )
        )
        types_seen = {e["relationship_type"] for e in result["chain"]}
        assert "imports" not in types_seen, (
            "Filter should exclude 'imports' edges when only 'caused_by' requested"
        )

    def test_filter_excludes_non_matching_type(self):
        from mcp_server.handlers.get_causal_chain import _handler_impl

        store = _get_store()
        src_id = _insert_entity(store, "ExclSrc", "concept")
        tgt_id = _insert_entity(store, "ExclTgt", "concept")
        _insert_relationship(store, src_id, tgt_id, "imports")

        # Ask only for "caused_by" — the "imports" edge must not appear
        result = _run(
            _handler_impl(
                {
                    "entity_name": "ExclSrc",
                    "relationship_types": ["caused_by"],
                }
            )
        )
        assert result["total_edges"] == 0 or all(
            e["relationship_type"] == "caused_by" for e in result["chain"]
        )


# ── P7 — Direction ───────────────────────────────────────────────────────


class TestDirection:
    """P7: direction parameter restricts traversal direction."""

    def test_outgoing_sees_edges_from_seed(self):
        from mcp_server.handlers.get_causal_chain import _handler_impl

        store = _get_store()
        a_id = _insert_entity(store, "DirA", "concept")
        b_id = _insert_entity(store, "DirB", "concept")
        # A causes B (outgoing from A)
        _insert_relationship(store, a_id, b_id, "caused_by")

        result = _run(_handler_impl({"entity_name": "DirA", "direction": "outgoing"}))
        # At minimum, the direct edge A→B must appear
        assert result["total_edges"] >= 1

    def test_incoming_sees_edges_targeting_seed(self):
        from mcp_server.handlers.get_causal_chain import _handler_impl

        store = _get_store()
        a_id = _insert_entity(store, "IncomingA", "concept")
        b_id = _insert_entity(store, "IncomingB", "concept")
        # B caused_by A (B is target); querying from B with "incoming"
        _insert_relationship(store, a_id, b_id, "caused_by")

        result = _run(
            _handler_impl({"entity_name": "IncomingB", "direction": "incoming"})
        )
        assert result["total_edges"] >= 1

    def test_direction_stored_in_result(self):
        from mcp_server.handlers.get_causal_chain import _handler_impl

        store = _get_store()
        src_id = _insert_entity(store, "DirCheck", "concept")
        tgt_id = _insert_entity(store, "DirCheckTgt", "concept")
        _insert_relationship(store, src_id, tgt_id, "depends_on")

        for direction in ("outgoing", "incoming", "both"):
            result = _run(
                _handler_impl({"entity_name": "DirCheck", "direction": direction})
            )
            assert result.get("direction") == direction


# ── P8 — Schema ───────────────────────────────────────────────────────────


class TestSchema:
    """P8: the tool schema is present and correctly structured."""

    def test_schema_exists(self):
        from mcp_server.handlers.get_causal_chain import schema

        assert isinstance(schema, dict)

    def test_schema_has_description(self):
        from mcp_server.handlers.get_causal_chain import schema

        assert "description" in schema
        assert schema["description"]

    def test_schema_has_input_schema(self):
        from mcp_server.handlers.get_causal_chain import schema

        assert "inputSchema" in schema

    def test_schema_input_properties_include_expected_keys(self):
        from mcp_server.handlers.get_causal_chain import schema

        props = schema["inputSchema"]["properties"]
        for key in ("entity_name", "memory_id", "max_depth", "direction"):
            assert key in props, f"inputSchema missing property: {key}"

    def test_direction_enum_values(self):
        from mcp_server.handlers.get_causal_chain import schema

        direction_enum = schema["inputSchema"]["properties"]["direction"]["enum"]
        assert set(direction_enum) == {"outgoing", "incoming", "both"}
