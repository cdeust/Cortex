"""Liskov contract enforcement: every registered MCP tool returns a dict.

Issue #17 (PSGSupport) — three handlers (remember, recall, get_telemetry)
were JSON-encoding their return values to strings before FastMCP saw
them. The MCP SDK rejects strings when an ``output_schema`` is declared:

    structured_content must be a dict or None. Got str: '{...}'

The fix moved ``safe_handler`` to return a dict directly. This test
pins the invariant: every tool registered on the MCPServer instance
declares ``return_type == dict`` (or a strict subtype). A handler that
silently regresses to ``-> str`` will fail this test before it ships.

mcp 2.0.0 migration (PR #331): the return-annotation check reads
``inspect.signature(tool.fn).return_annotation`` — the internal
``mcp.server.mcpserver.tools.base.Tool`` has no ``return_type`` attribute
(verified: ``hasattr(tool, "return_type")`` is ``False`` against the
installed mcp==2.0.0, 2026-08-10; FastMCP's ``Tool`` carried one). Also
now requires the PARAMETRIZED ``dict[str, Any]``, not bare ``dict``: mcp
2.0.0 only derives structured output (and therefore a real
``output_schema``) from a parametrized generic — a bare ``dict`` return
produces ``output_schema=None`` and no ``structuredContent`` at all, a
correctness regression the second test class below exists to catch (see
``mcp_server/handlers/_tool_meta.py``'s ``apply_output_schemas``
docstring for the full mechanism).
"""

from __future__ import annotations

import asyncio
import inspect
import json
import typing

import pytest
from mcp.server.mcpserver import MCPServer

from mcp_server import (
    tool_registry_advanced,
    tool_registry_core,
    tool_registry_ingest,
    tool_registry_manage,
    tool_registry_memory,
    tool_registry_nav,
    tool_registry_wiki,
)


def _build_mcp_with_all_tools() -> MCPServer:
    """Construct an MCPServer instance with every tool registered.

    Mirrors mcp_server.__main__ so the test exercises the production
    registration path. No I/O or DB is touched at registration time;
    handlers are only constructed, not invoked.
    """
    mcp = MCPServer(name="contract-test", version="0.0.0")
    tool_registry_core.register(mcp)
    tool_registry_memory.register(mcp)
    tool_registry_manage.register(mcp)
    tool_registry_nav.register(mcp)
    tool_registry_advanced.register(mcp)
    tool_registry_wiki.register(mcp)
    tool_registry_ingest.register(mcp)
    return mcp


def _is_dict_return_type(return_type: typing.Any) -> bool:
    """True iff ``return_type`` is ``dict`` or a parametrized dict alias."""
    if return_type is dict:
        return True
    origin = typing.get_origin(return_type)
    return origin is dict


def _return_annotation_of(tool: typing.Any) -> typing.Any:
    """The wrapped tool function's declared return type.

    ``inspect.signature(..., eval_str=True)`` matches how mcp 2.0.0's own
    ``func_metadata`` resolves annotations (see
    ``mcp.server.mcpserver.utilities.func_metadata``), so a string
    annotation under ``from __future__ import annotations`` resolves the
    same way here as it does for the SDK's own structured-output
    derivation — the two must agree for this test to mean anything.
    """
    return inspect.signature(tool.fn, eval_str=True).return_annotation


@pytest.fixture(scope="module")
def all_registered_tools():
    mcp = _build_mcp_with_all_tools()
    return mcp._tool_manager.list_tools()


def test_at_least_one_tool_registered(all_registered_tools):
    """Sanity: registration produced tools (otherwise the test is vacuous)."""
    assert len(all_registered_tools) > 0


def test_every_tool_declares_dict_return_type(all_registered_tools):
    """Liskov: every MCP tool returns a dict, not a str.

    Issue #17 root cause: ``safe_handler`` JSON-encoded the dict before
    return, breaking the contract for handlers that declare
    ``output_schema``. This assertion fails the build if any new
    handler regresses to ``-> str``.
    """
    offenders = []
    for tool in all_registered_tools:
        rt = _return_annotation_of(tool)
        if not _is_dict_return_type(rt):
            offenders.append((tool.name, rt))

    assert not offenders, (
        "These handlers do not return a dict (issue #17 contract):\n"
        + "\n".join(f"  - {name}: {rt!r}" for name, rt in offenders)
    )


def test_tools_with_output_schema_have_dict_return_type(all_registered_tools):
    """When ``output_schema`` is declared, the MCP SDK rejects non-dict returns.

    This is the exact failure PSGSupport hit. A handler that declares
    a schema but returns a string is shipping a runtime error.
    """
    offenders = []
    for tool in all_registered_tools:
        if tool.output_schema is None:
            continue
        rt = _return_annotation_of(tool)
        if not _is_dict_return_type(rt):
            offenders.append((tool.name, rt))

    assert not offenders, (
        "Handlers declare output_schema but do not return dict — "
        "the MCP SDK will reject these at runtime (issue #17):\n"
        + "\n".join(f"  - {name}: {rt!r}" for name, rt in offenders)
    )


class TestWireValuesAreJsonNative:
    """Issue #17 part 2 (2026-06-23): the dict-return contract is necessary
    but not sufficient. A handler can return a dict whose VALUES are not
    JSON-native — the PostgreSQL store yields ``numpy.float32`` scores and
    ``datetime`` timestamps where the SQLite store yields ``float``/``str``.
    The MCP SDK can only build ``structuredContent`` from JSON-serializable
    values, so a non-native field silently drops structuredContent and the
    Claude Code client rejects the call ("outputSchema defined but no
    structured output returned"). This passed CI because the suite ran on
    SQLite (native types) and asserted key presence, never serializability.

    ``safe_handler`` normalizes at the one boundary every handler crosses,
    so every backend's output is JSON-native and identical in type. Pinned
    here with a fake PG-shaped handler — no DB, backend-agnostic, fails
    regardless of which store the suite runs against.
    """

    def test_safe_handler_renders_pg_like_output_json_serializable(self):
        import datetime as dt

        import numpy as np

        from mcp_server.tool_error_handler import safe_handler

        async def pg_like_handler(_args):
            # Mirrors a PostgreSQL recall row exactly: numpy score + tz-aware
            # datetime. Raised "Object of type float32 is not JSON
            # serializable" before the boundary normalizer existed.
            return {
                "memories": [
                    {
                        "memory_id": np.int64(4202320),
                        "score": np.float32(0.0026),
                        "created_at": dt.datetime(
                            2026, 6, 10, 13, 19, 31, tzinfo=dt.timezone.utc
                        ),
                    }
                ],
                "count": 1,
            }

        result = asyncio.run(safe_handler(pg_like_handler, {"query": "x"}))
        # The exact wire requirement the MCP SDK imposes on structuredContent.
        json.dumps(result)  # must not raise
        mem = result["memories"][0]
        assert isinstance(mem["score"], float)
        assert isinstance(mem["created_at"], str)
        assert isinstance(mem["memory_id"], int)
