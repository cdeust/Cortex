"""#559 gate 2: newly-exposed parameters actually reach the handler when
invoked through the REGISTERED MCP tool (``mcp.call_tool``), not just
through a direct Python call to the handler function.

test_tool_schema_parity.py proves the wrapper SIGNATURE now matches the
handler's declared inputSchema (static, schema-level). This file proves
the dynamic half: a client calling the registered tool with one of the
parameters #559 exposed actually gets it forwarded into the handler's
``args`` dict — the concrete downstream effect named in issue #559 (the
host protocol's ``recall(tags_any=["archival"])`` and the
cortex-remember-global skill's ``is_global: true``).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from mcp.server.mcpserver import MCPServer

from mcp_server import tool_registry_memory as registry
from mcp_server.handlers import recall, remember


def _server() -> MCPServer:
    return MCPServer(name="reachability-test")


def test_recall_tool_call_forwards_tags_any_to_the_handler():
    """``recall(tags_any=["archival"])`` — the host protocol's prescribed
    call for the archival tier — must reach recall.handler's args dict
    when invoked through the registered MCP tool."""
    mcp = _server()
    with patch.dict("os.environ", {"CORTEX_ROOT_AGENT_TOPIC": ""}):
        registry._register_recall(mcp)
        spy = AsyncMock(return_value={"memories": [], "count": 0, "intent": "general"})
        with patch.object(recall, "handler", spy):
            asyncio.run(
                mcp.call_tool(
                    "recall",
                    {"query": "anything", "tags_any": ["archival"]},
                )
            )
    received_args = spy.call_args.args[0]
    assert received_args["tags_any"] == ["archival"]


def test_remember_tool_call_forwards_is_global_to_the_handler():
    """``remember(is_global=True)`` — what the cortex-remember-global
    skill sends — must reach remember.handler's args dict when invoked
    through the registered MCP tool."""
    mcp = _server()
    with patch.dict("os.environ", {"CORTEX_ROOT_AGENT_TOPIC": ""}):
        registry._register_remember(mcp)
        spy = AsyncMock(return_value={"stored": True, "action": "stored"})
        with patch.object(remember, "handler", spy):
            asyncio.run(
                mcp.call_tool(
                    "remember",
                    {"content": "a durable fact", "is_global": True},
                )
            )
    received_args = spy.call_args.args[0]
    assert received_args["is_global"] is True
