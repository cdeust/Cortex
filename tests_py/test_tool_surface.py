"""The advertised tool surface is read from the registries, not restated.

`scripts/verify_mcp_hosts.py` carried its own literal floor of 52 while the
surface moved to 54 (ADR-1066), and nothing noticed until the count reached
57 and broke that script's ceiling in CI (issue #597).

source: ADR-1077
"""

from __future__ import annotations

import asyncio

from mcp.server.mcpserver import MCPServer

from mcp_server.__main__ import register_all
from mcp_server.tool_surface import UPSTREAM_TOOL_NAMES, standalone_tool_names


def _live(*, codebase: bool, prd: bool) -> set[str]:
    server = MCPServer(name="surface-test", version="0.0.0")
    register_all(server, codebase=codebase, prd=prd)
    return {tool.name for tool in asyncio.run(server.list_tools())}


def test_the_derived_surface_is_what_registers() -> None:
    assert standalone_tool_names() == _live(codebase=False, prd=False)


def test_the_upstream_names_are_exactly_the_gated_ones() -> None:
    gated = _live(codebase=True, prd=True) - _live(codebase=False, prd=False)

    assert gated == set(UPSTREAM_TOOL_NAMES)


def test_the_host_contract_bounds_follow_the_surface() -> None:
    from scripts.verify_mcp_hosts import MAX_FULL_TOOL_COUNT, MIN_FULL_TOOL_COUNT

    assert MIN_FULL_TOOL_COUNT == len(standalone_tool_names())
    assert MAX_FULL_TOOL_COUNT == MIN_FULL_TOOL_COUNT + len(UPSTREAM_TOOL_NAMES)
