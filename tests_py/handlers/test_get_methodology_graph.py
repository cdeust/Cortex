"""Tests for mcp_server.handlers.get_methodology_graph — ported from get-methodology-graph.test.js."""

import asyncio

from mcp_server.handlers.get_methodology_graph import handler


class TestGetMethodologyGraphHandler:
    def test_returns_nodes_edges_blindspots(self):
        result = asyncio.run(handler())
        assert result is not None
        assert "nodes" in result
        assert isinstance(result["nodes"], list)
        assert "edges" in result
        assert isinstance(result["edges"], list)
        assert "blindSpotRegions" in result
        assert isinstance(result["blindSpotRegions"], list)

    def test_accepts_domain_filter(self):
        result = asyncio.run(handler({"domain": "nonexistent-domain"}))
        assert result is not None
        assert isinstance(result["nodes"], list)
        assert isinstance(result["edges"], list)
