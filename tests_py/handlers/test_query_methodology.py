"""Tests for mcp_server.handlers.query_methodology — ported from query-methodology.test.js."""

import asyncio

from mcp_server.handlers.query_methodology import handler


class TestQueryMethodologyHandler:
    def test_response_shape_no_args(self):
        result = asyncio.run(handler())
        assert result is not None
        assert "domain" in result
        assert "confidence" in result
        assert "coldStart" in result
        assert "context" in result
        assert isinstance(result["context"], str)
        assert "entryPoints" in result
        assert isinstance(result["entryPoints"], list)
        assert "recurringPatterns" in result
        assert isinstance(result["recurringPatterns"], list)
        assert "toolPreferences" in result
        assert "blindSpots" in result
        assert isinstance(result["blindSpots"], list)
        assert "connectionBridges" in result
        assert "sessionCount" in result
        assert isinstance(result["sessionCount"], (int, float))
        # Memory integration fields
        assert "hotMemories" in result
        assert isinstance(result["hotMemories"], list)
        assert "firedTriggers" in result
        assert isinstance(result["firedTriggers"], list)

    def test_response_shape_with_cwd(self):
        result = asyncio.run(handler({"cwd": "/tmp/test-project"}))
        assert result is not None
        assert "domain" in result
        assert "context" in result

    def test_response_shape_with_project(self):
        result = asyncio.run(handler({"project": "test-project"}))
        assert result is not None
        assert "confidence" in result
        assert isinstance(result["confidence"], (int, float))
