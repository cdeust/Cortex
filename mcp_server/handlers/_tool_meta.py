"""Shared tool-metadata helpers for MCP registration.

Glama's tool score is dominated by three fields most of our handlers
were missing:

1. ``title`` — human-readable name shown in tool lists.
2. ``output_schema`` — declared return-shape JSON Schema. Lets callers
   validate responses + enables type-aware completion in the client.
3. ``annotations`` — ``readOnlyHint`` / ``destructiveHint`` /
   ``idempotentHint`` / ``openWorldHint`` (spec: MCP 2024-11-05+).

Every handler schema dict may carry these keys; ``tool_kwargs()`` pulls
whichever ``MCPServer.tool()`` accepts as constructor kwargs (``title``,
``description``, ``annotations``) and returns a kwargs mapping ready to
hand to ``mcp.tool(**...)``. The helper tolerates missing keys so the
upgrade is incremental — handlers that have been refreshed light up with
the full metadata; older handlers keep their existing description-only
registration until they're touched.

``output_schema`` is NOT among ``tool_kwargs()``'s returned keys (mcp 2.0.0
migration, PR #331) — see ``apply_output_schemas`` below for why and how it
is still applied. ``tags`` is no longer extracted at all: no handler schema
in this repo ever declared one (verified by grep across
``mcp_server/handlers/*.py``, 2026-08-10), and ``MCPServer.tool()`` has no
``tags`` parameter to receive it if one existed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

# Named annotation presets so every handler converges on the same
# semantics. Presets name the CAPABILITY, not the handler.

# Pure read. Safe to call repeatedly. No state change.
READ_ONLY: dict[str, Any] = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}

# Reads and produces new state, but running twice has the same effect
# as running once (e.g. storing a memory that dedups / merges).
IDEMPOTENT_WRITE: dict[str, Any] = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}

# Writes new state on every call; subsequent calls produce new rows.
NON_IDEMPOTENT_WRITE: dict[str, Any] = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": False,
}

# Mutates or removes existing state in a way that can't be undone
# without data loss.
DESTRUCTIVE: dict[str, Any] = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": True,
    "openWorldHint": False,
}

# Read-only but reaches to external state (browser, subprocess,
# filesystem outside our DB).
READ_ONLY_EXTERNAL: dict[str, Any] = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}


def tool_kwargs(schema: dict[str, Any]) -> dict[str, Any]:
    """Extract ``mcp.tool(**kwargs)`` constructor kwargs from a handler schema.

    Returns only keys ``MCPServer.tool()`` itself accepts: ``description``,
    ``title``, ``annotations`` (verified against the installed mcp==2.0.0
    signature — it also takes ``name``, ``icons``, ``meta``,
    ``structured_output``, none of which handler schemas populate here).
    ``output_schema`` is handled separately by ``apply_output_schemas``
    (below) because ``MCPServer.tool()`` has no parameter for a raw JSON
    Schema at all — mcp 2.0.0 derives structured output exclusively from
    the wrapped function's return type annotation, never from a
    hand-authored dict passed at registration time.
    """
    out: dict[str, Any] = {}
    if "description" in schema:
        out["description"] = schema["description"]
    if "title" in schema:
        out["title"] = schema["title"]
    if "annotations" in schema:
        out["annotations"] = schema["annotations"]
    return out


def _output_schema_of(schema: Mapping[str, Any]) -> dict[str, Any] | None:
    """Read a handler schema's declared output shape, snake or camel key."""
    if "output_schema" in schema:
        return schema["output_schema"]
    if "outputSchema" in schema:
        return schema["outputSchema"]
    return None


def apply_output_schemas(
    mcp: MCPServer, schemas: Mapping[str, Mapping[str, Any]]
) -> None:
    """Attach each handler's hand-authored ``outputSchema`` to its tool.

    mcp 2.0.0's ``MCPServer.tool()`` derives ``Tool.output_schema`` solely
    from the wrapped function's return type annotation (via
    ``func_metadata(structured_output=...)``) — there is no constructor
    parameter to pass a raw JSON Schema instead, and Cortex's handlers
    return a plain ``dict`` (the annotation FastMCP-era ``output_schema``
    kwarg used to carry the real shape for). Rewriting every handler's
    return type to a matching Pydantic/TypedDict model would reproduce the
    same wire shape at a much larger diff; this does it directly instead.

    ``Tool.output_schema`` (``mcp.server.mcpserver.tools.base.Tool``,
    the SERVER-SIDE registered tool, not the per-call wire
    ``mcp.types.Tool``) is a ``functools.cached_property`` reading
    ``self.fn_metadata.output_schema`` — but a ``cached_property`` is a
    descriptor with normal instance-``__dict__`` precedence, so assigning
    ``tool.output_schema = {...}`` directly overrides it, and that
    override persists: ``mcp._tool_manager.list_tools()`` returns the
    SAME internal ``Tool`` objects on every call (unlike the wire-level
    ``MCPServer.list_tools()``, which rebuilds a fresh ``mcp.types.Tool``
    envelope, reading ``info.output_schema``, on every call — see
    ``apply_param_docs`` below for the same distinction on the input
    side). Verified in an isolated venv, mcp==2.0.0, 2026-08-10: setting
    the internal tool's ``output_schema`` before any ``tools/list`` call
    is reflected in every subsequent wire-level ``tools/list`` response.

    Must run with no event loop active (composition-root import time,
    before ``mcp.run()``), same constraint as ``apply_param_docs``.
    """
    for tool in mcp._tool_manager.list_tools():
        handler_schema = schemas.get(tool.name)
        if handler_schema is None:
            continue
        output_schema = _output_schema_of(handler_schema)
        if output_schema is not None:
            tool.output_schema = output_schema


def apply_param_docs(mcp: MCPServer, schemas: Mapping[str, Mapping[str, Any]]) -> None:
    """Merge hand-written ``inputSchema`` parameter descriptions into the
    signature-derived schemas MCPServer registered.

    MCPServer builds each tool's input schema from the Python function
    signature, so parameter descriptions authored in handler schema dicts
    never reach the client on their own. This post-registration pass
    copies each documented property's ``description`` onto the derived
    schema. Descriptions only — types, defaults, and required-ness stay
    signature-derived. Registered tools absent from ``schemas``, and
    parameters the handler schema does not document, are left untouched.

    Reads from ``mcp._tool_manager.list_tools()`` (the persistent internal
    ``Tool`` registry, mutable — see ``apply_output_schemas``'s docstring
    for why), not the async wire-level ``mcp.list_tools()``: under mcp
    2.0.0 the latter rebuilds a fresh ``mcp.types.Tool`` per call, so
    mutating its ``.input_schema`` would be silently discarded on the next
    ``tools/list`` — verified in an isolated venv, mcp==2.0.0, 2026-08-10.
    No longer async (the internal registry read is synchronous), so the
    caller no longer needs ``asyncio.run`` — kept as a thin sync wrapper
    for call-site compatibility with the composition root.
    """
    for tool in mcp._tool_manager.list_tools():
        handler_schema = schemas.get(tool.name)
        if handler_schema is None:
            continue
        documented = handler_schema.get("inputSchema", {}).get("properties", {})
        derived = tool.parameters.get("properties", {})
        for param_name, param_schema in derived.items():
            description = documented.get(param_name, {}).get("description")
            if description and "description" not in param_schema:
                param_schema["description"] = description
