"""Shared tool-metadata helpers for MCP registration.

source: ADR-0327"""

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

    Returns the accepted ``MCPServer.tool()`` keys populated by handler schemas:
    ``description``, ``title``, and ``annotations``. ``output_schema`` is applied
    separately by ``apply_output_schemas``.

    source: ADR-0327"""
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

        Must run with no event loop active (composition-root import time,
        before ``mcp.run()``), same constraint as ``apply_param_docs``.

    source: ADR-0327"""
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

    source: ADR-0327"""
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


# Root-level JSON Schema combinators that state a cross-parameter constraint
# which ``required`` cannot ("one of", "if A then B").
_CONSTRAINT_KEYWORDS = ("anyOf", "oneOf", "allOf", "dependentRequired")


def _cited_properties(keyword: str, value: Any) -> set[str]:
    """Property names a combinator refers to (``required`` lists, and the
    keys and values of ``dependentRequired``)."""
    if keyword == "dependentRequired":
        return set(value) | {name for names in value.values() for name in names}
    return {name for branch in value for name in branch.get("required", [])}


def apply_input_constraints(
    mcp: MCPServer, schemas: Mapping[str, Mapping[str, Any]]
) -> None:
    """Publish each handler's root-level cross-parameter constraints.

        Copies ``anyOf`` / ``oneOf`` / ``allOf`` / ``dependentRequired`` from the
        handler's ``inputSchema`` onto the signature-derived schema so clients
        can reject an invalid call before sending it. Publication only: the
        handler remains the sole enforcement point (the SDK validates against
        the wrapper signature, never this dict). ``required`` is never copied
        (it is signature-derived). Raises ``ValueError`` when a combinator
        cites a property the wrapper signature does not expose.

    source: ADR-0327"""
    for tool in mcp._tool_manager.list_tools():
        declared = schemas.get(tool.name, {}).get("inputSchema", {})
        known = set(tool.parameters.get("properties", {}))
        for keyword in _CONSTRAINT_KEYWORDS:
            if keyword not in declared:
                continue
            unknown = _cited_properties(keyword, declared[keyword]) - known
            if unknown:
                raise ValueError(
                    f"{tool.name}: {keyword} cites {sorted(unknown)}, which the "
                    f"registered wrapper does not expose"
                )
            tool.parameters[keyword] = declared[keyword]
