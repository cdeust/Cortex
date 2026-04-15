"""Tests for tool registration — verify tier-1 tools are registered via FastMCP."""

import asyncio

from mcp_server.__main__ import mcp


class TestRegistry:
    def test_has_all_tier1_tools(self):
        tools = asyncio.run(mcp.list_tools())
        tool_names = {t.name for t in tools}
        expected = [
            "query_methodology",
            "detect_domain",
            "rebuild_profiles",
            "list_domains",
            "record_session_end",
            "get_methodology_graph",
            "open_visualization",
            "explore_features",
        ]
        for name in expected:
            assert name in tool_names, f"Missing tool: {name}"

    def test_each_tool_has_description(self):
        tools = asyncio.run(mcp.list_tools())
        for tool in tools:
            assert tool.description, f"{tool.name} missing description"
