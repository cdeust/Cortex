"""Tests for tool registration — verify tier-1 tools are registered via the MCP SDK."""

import asyncio

from mcp_server.__main__ import mcp


class TestRegistry:
    def test_has_all_tier1_tools(self):
        tools = asyncio.run(mcp.list_tools())
        tool_names = {t.name for t in tools}
        # Visualization tools (get_methodology_graph, open_visualization,
        # query_workflow_graph) were extracted to the cortex-viz MCP.
        expected = [
            "query_methodology",
            "detect_domain",
            "rebuild_profiles",
            "list_domains",
            "record_session_end",
            "explore_features",
        ]
        for name in expected:
            assert name in tool_names, f"Missing tool: {name}"

    def test_each_tool_has_description(self):
        tools = asyncio.run(mcp.list_tools())
        for tool in tools:
            assert tool.description, f"{tool.name} missing description"
