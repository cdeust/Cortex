"""Input-schema parity between handler schemas and registered MCP wrappers
(#98 regression guard, widened to every registered tool by #559).

The client-visible input schema is whatever the MCP SDK derives from the
REGISTERED WRAPPER's signature (``tool_registry_*.py``), not from the
handler's own ``schema["inputSchema"]`` dict. If a handler gains a new
parameter (or an enum value) but the wrapper signature is never updated
to match, the parameter silently becomes unreachable over MCP even
though the handler-level schema documents it — and the reverse drift
(a wrapper parameter the handler's own schema never declared) is exactly
as dangerous: a client can pass it, FastMCP will accept it, and the
handler will silently ignore it forever.

This test iterates ``mcp.list_tools()`` — the live, post-registration
truth — and asserts, for EVERY registered tool with a handler schema
entry, that the wrapper's parameter set and the handler's own
``inputSchema["properties"]`` are exactly equal, with NO per-tool
omission list. The only structural exception is the documented
rooted-agent_topic variant (``CORTEX_ROOT_AGENT_TOPIC``): the server
deliberately drops ``agent_topic`` from the client-visible schema in
that mode and forces the scope at the handler boundary instead (see
``tool_registry_memory.py::_register_remember``/``_register_recall``).

Measured at a3b3a79d (pre-fix): 13 of 54 tools dropped handler-declared
properties — this test fails on that commit and passes after the #559
fix. ``ingest_prd``'s ``SCHEMAS`` entry exists but the tool itself is
conditionally registered (gated on ``prd_upstream_available()``); it is
skipped here rather than asserted on, matching ``merged_schemas()``'s
own model of "one static schema map, a possibly-smaller live tool set".
"""

from __future__ import annotations

import asyncio

from mcp_server.__main__ import merged_schemas, mcp
from mcp_server.infrastructure.memory_config import root_agent_topic

# agent_topic is DELIBERATELY omitted from the "rooted" remember/recall
# wrapper variants when CORTEX_ROOT_AGENT_TOPIC is set (server forces the
# scope instead) — see tool_registry_memory.py::_register_remember and
# _register_recall. When a test environment happens to run rooted,
# exclude it from the equality check; unrooted (the default in this
# suite) exposes agent_topic and the exclusion set is empty.
_ROOTED_OMISSIONS: set[str] = (
    {"agent_topic"} if root_agent_topic() is not None else set()
)


def _live_tools() -> dict[str, set[str]]:
    """tool_name -> the parameter names the MCP SDK actually derived from
    the registered wrapper's signature — the client-visible truth. Reads
    ``.input_schema`` (the wire-level ``mcp.types.Tool`` field mcp 2.0.0
    uses — was ``.parameters`` under FastMCP; verified against the
    installed mcp==2.0.0, 2026-08-10)."""
    tools = asyncio.run(mcp.list_tools())
    return {t.name: set(t.input_schema.get("properties", {}).keys()) for t in tools}


def test_every_registered_tool_matches_its_handler_schema_exactly() -> None:
    schemas = merged_schemas()
    live = _live_tools()
    failures: list[str] = []
    for tool_name, wrapper_params in live.items():
        handler_schema = schemas.get(tool_name)
        if handler_schema is None:
            # No handler-schema entry to compare against (would itself be
            # a bug for any real tool, but merged_schemas()'s own callers
            # already assume every registered tool has one — nothing this
            # test needs to invent a separate assertion for).
            continue
        handler_props = set(
            handler_schema.get("inputSchema", {}).get("properties", {}).keys()
        )
        omit = _ROOTED_OMISSIONS if "agent_topic" in handler_props else set()
        missing = (handler_props - omit) - wrapper_params
        extra = wrapper_params - handler_props
        if missing:
            failures.append(
                f"{tool_name}: handler declares {sorted(missing)} but the "
                f"registered wrapper does not expose them (#559)"
            )
        if extra:
            failures.append(
                f"{tool_name}: wrapper exposes {sorted(extra)} but the "
                f"handler's own inputSchema never declared them — wrapper-"
                f"side drift with no handler contract behind it"
            )
    assert not failures, "\n".join(failures)


def test_every_tool_name_in_schemas_is_either_registered_or_gated() -> None:
    """Every ``merged_schemas()`` entry either has a live registered tool,
    or is a known upstream-gated tool (``ingest_prd``, registered only
    when ``prd_upstream_available()``) — never a stale/typo'd map key."""
    schemas = merged_schemas()
    live_names = set(_live_tools())
    unaccounted = set(schemas) - live_names - {"ingest_prd"}
    assert not unaccounted, (
        f"schema map declares tool(s) with no registered wrapper and no "
        f"known gating: {sorted(unaccounted)}"
    )
