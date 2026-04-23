"""Unit tests for the query_workflow_graph handler (Gap 1)."""

from __future__ import annotations

import pytest

from mcp_server.handlers.query_workflow_graph import (
    _apply_filters,
    _as_set,
    _bfs_neighbourhood,
    handler,
)


# ── Baseline graph used by most tests ─────────────────────────────────

_GRAPH = {
    "nodes": [
        {"id": "domain:cortex", "kind": "domain", "heat": 0.0},
        {"id": "file:aaa", "kind": "file", "heat": 0.5},
        {"id": "file:bbb", "kind": "file", "heat": 0.3},
        {"id": "symbol:s1", "kind": "symbol", "heat": 0.8},
        {"id": "symbol:s2", "kind": "symbol", "heat": 0.2},
        {"id": "symbol:s3", "kind": "symbol", "heat": 0.1},
        {"id": "memory:42", "kind": "memory", "heat": 0.7},
    ],
    "edges": [
        {"source": "file:aaa", "target": "domain:cortex", "kind": "in_domain"},
        {"source": "file:bbb", "target": "domain:cortex", "kind": "in_domain"},
        {"source": "symbol:s1", "target": "file:aaa", "kind": "defined_in"},
        {"source": "symbol:s2", "target": "file:aaa", "kind": "defined_in"},
        {"source": "symbol:s3", "target": "file:bbb", "kind": "defined_in"},
        {"source": "symbol:s1", "target": "symbol:s2", "kind": "calls"},
        {"source": "symbol:s2", "target": "symbol:s3", "kind": "calls"},
        {"source": "memory:42", "target": "symbol:s1", "kind": "about_entity"},
    ],
    "meta": {"schema": "workflow_graph.v1"},
}


# ── _as_set ───────────────────────────────────────────────────────────


class TestAsSet:
    def test_none_yields_none(self):
        assert _as_set(None) is None

    def test_empty_string_yields_none(self):
        assert _as_set("") is None

    def test_string_wrapped_in_set(self):
        assert _as_set("calls") == {"calls"}

    def test_list_converted(self):
        assert _as_set(["calls", "imports"]) == {"calls", "imports"}

    def test_list_drops_empties(self):
        assert _as_set(["calls", "", None]) == {"calls"}

    def test_empty_list_yields_none(self):
        assert _as_set([]) is None

    def test_unknown_type_yields_none(self):
        assert _as_set(42) is None


# ── BFS ───────────────────────────────────────────────────────────────


class TestBfsNeighbourhood:
    def test_depth_1_finds_direct_neighbours(self):
        reached, edges = _bfs_neighbourhood(
            _GRAPH["nodes"], _GRAPH["edges"], "file:aaa", depth=1
        )
        # file:aaa connects to: domain:cortex, symbol:s1, symbol:s2
        assert reached == {
            "file:aaa",
            "domain:cortex",
            "symbol:s1",
            "symbol:s2",
        }
        # Edges must have both endpoints in the reached set
        for e in edges:
            assert e["source"] in reached and e["target"] in reached

    def test_depth_2_extends_to_two_hops(self):
        reached, _ = _bfs_neighbourhood(
            _GRAPH["nodes"], _GRAPH["edges"], "file:aaa", depth=2
        )
        # +file:bbb (through domain:cortex), +symbol:s3 (through symbol:s2),
        # +memory:42 (through symbol:s1)
        assert reached == {
            "file:aaa",
            "domain:cortex",
            "symbol:s1",
            "symbol:s2",
            "symbol:s3",
            "file:bbb",
            "memory:42",
        }

    def test_depth_0_is_seed_only(self):
        reached, edges = _bfs_neighbourhood(
            _GRAPH["nodes"], _GRAPH["edges"], "file:aaa", depth=0
        )
        assert reached == {"file:aaa"}
        assert edges == []

    def test_unknown_seed_returns_singleton(self):
        reached, edges = _bfs_neighbourhood(
            _GRAPH["nodes"], _GRAPH["edges"], "does-not-exist", depth=1
        )
        assert reached == {"does-not-exist"}
        assert edges == []


# ── _apply_filters ────────────────────────────────────────────────────


class TestApplyFilters:
    def _keys(self, g, field):
        return (
            {n["id"] for n in g[field]}
            if field == "nodes"
            else [(e["source"], e["target"], e["kind"]) for e in g["edges"]]
        )

    def test_no_filters_returns_full_graph(self):
        r = _apply_filters(
            _GRAPH,
            node_kinds=None,
            edge_kinds=None,
            neighbour_of=None,
            depth=1,
            limit_nodes=500,
        )
        assert len(r["nodes"]) == len(_GRAPH["nodes"])
        assert len(r["edges"]) == len(_GRAPH["edges"])
        assert r["meta"]["filtered"] is True

    def test_edge_kind_filter(self):
        r = _apply_filters(
            _GRAPH,
            node_kinds=None,
            edge_kinds={"calls"},
            neighbour_of=None,
            depth=1,
            limit_nodes=500,
        )
        assert {e["kind"] for e in r["edges"]} == {"calls"}
        assert r["meta"]["filter"]["edge_kind"] == ["calls"]

    def test_node_kind_filter_prunes_dangling_edges(self):
        """Keeping only ``symbol`` nodes must also drop edges whose
        other endpoint is a file or domain — no dangling edges."""
        r = _apply_filters(
            _GRAPH,
            node_kinds={"symbol"},
            edge_kinds=None,
            neighbour_of=None,
            depth=1,
            limit_nodes=500,
        )
        assert {n["kind"] for n in r["nodes"]} == {"symbol"}
        node_ids = {n["id"] for n in r["nodes"]}
        for e in r["edges"]:
            assert e["source"] in node_ids
            assert e["target"] in node_ids

    def test_neighbour_of_returns_khop(self):
        r = _apply_filters(
            _GRAPH,
            node_kinds=None,
            edge_kinds=None,
            neighbour_of="symbol:s1",
            depth=1,
            limit_nodes=500,
        )
        ids = {n["id"] for n in r["nodes"]}
        # s1's direct neighbours: file:aaa, symbol:s2, memory:42
        assert ids == {"symbol:s1", "file:aaa", "symbol:s2", "memory:42"}

    def test_limit_nodes_trims_by_heat_and_reports_truncated(self):
        r = _apply_filters(
            _GRAPH,
            node_kinds=None,
            edge_kinds=None,
            neighbour_of=None,
            depth=1,
            limit_nodes=3,
        )
        assert len(r["nodes"]) == 3
        # Trimmed in heat-descending order — top 3 are s1 (0.8), mem42 (0.7),
        # file:aaa (0.5).
        top_ids = {n["id"] for n in r["nodes"]}
        assert "symbol:s1" in top_ids  # highest heat
        assert r["meta"]["truncated_nodes"] == len(_GRAPH["nodes"]) - 3

    def test_meta_records_filter(self):
        r = _apply_filters(
            _GRAPH,
            node_kinds={"symbol"},
            edge_kinds={"calls"},
            neighbour_of="symbol:s1",
            depth=2,
            limit_nodes=100,
        )
        f = r["meta"]["filter"]
        assert f["node_kind"] == ["symbol"]
        assert f["edge_kind"] == ["calls"]
        assert f["neighbour_of"] == "symbol:s1"
        assert f["depth"] == 2

    def test_bfs_runs_over_full_edges_then_edge_kind_slices(self):
        """Feynman audit invariant: ``neighbour_of=X + edge_kind=calls``
        means "all nodes within N hops of X on the FULL graph, then
        keep only call edges among them". BFS does NOT traverse only
        call edges. Documented in ``_apply_filters`` docstring; this
        test locks the contract so a future optimisation doesn't
        silently change the semantic."""
        r = _apply_filters(
            _GRAPH,
            node_kinds=None,
            edge_kinds={"calls"},
            neighbour_of="symbol:s1",
            depth=1,
            limit_nodes=500,
        )
        ids = {n["id"] for n in r["nodes"]}
        # BFS reaches file:aaa (via defined_in) and memory:42 (via
        # about_entity) despite edge_kind={calls} — because BFS ran
        # over the full edge set.
        assert "file:aaa" in ids
        assert "memory:42" in ids
        assert "symbol:s2" in ids  # reached via calls
        # But only call edges survive the edge_kind filter.
        assert {e["kind"] for e in r["edges"]} <= {"calls"}

    def test_node_kind_filter_produces_subgraph_without_in_domain_invariant(self):
        """Dijkstra audit concern #7: this handler's contract is "return
        a typed subgraph", not "return a full renderable graph". A
        ``node_kind={'symbol'}`` filter legitimately drops every
        in_domain edge. Lock the behaviour so nobody later adds a
        ``validate_graph`` call that would reject these slices."""
        r = _apply_filters(
            _GRAPH,
            node_kinds={"symbol"},
            edge_kinds=None,
            neighbour_of=None,
            depth=1,
            limit_nodes=500,
        )
        assert {n["kind"] for n in r["nodes"]} == {"symbol"}
        assert not any(e["kind"] == "in_domain" for e in r["edges"])


# ── handler integration ───────────────────────────────────────────────


class _FakeStore:
    """Stub store matching the subset of WorkflowGraphSource calls the
    handler triggers. All loaders return empty lists so the builder
    degrades to an empty graph — enough to verify the filter path runs
    end-to-end without a live PG connection."""

    def search_by_tag_vector(self, **_kw):
        return []

    def get_hot_memories(self, **_kw):
        return []

    def get_all_entities(self, **_kw):
        return []

    def list_memory_entity_edges(self):
        return []


@pytest.mark.asyncio
async def test_handler_returns_shaped_payload_on_empty_graph():
    result = await handler({"limit_nodes": 10}, store=_FakeStore())
    assert "nodes" in result
    assert "edges" in result
    assert "meta" in result
    assert result["meta"]["filter"]["limit_nodes"] == 10
    assert result["meta"]["filtered"] is True
