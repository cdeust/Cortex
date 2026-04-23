"""Shared tool-metadata helpers for MCP registration.

Glama's tool score is dominated by three fields most of our handlers
were missing:

1. ``title`` — human-readable name shown in tool lists.
2. ``output_schema`` — declared return-shape JSON Schema. Lets callers
   validate responses + enables type-aware completion in the client.
3. ``annotations`` — ``readOnlyHint`` / ``destructiveHint`` /
   ``idempotentHint`` / ``openWorldHint`` (spec: MCP 2024-11-05+).

Every handler schema dict may carry these keys; ``tool_kwargs()`` pulls
whichever are present and returns a kwargs mapping ready to hand to
``mcp.tool(**...)``. The helper tolerates missing keys so the upgrade
is incremental — handlers that have been refreshed light up with the
full metadata; older handlers keep their existing description-only
registration until they're touched.
"""

from __future__ import annotations

from typing import Any

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
    """Extract mcp.tool(**kwargs) from a handler schema dict.

    Returns the keys FastMCP accepts: ``description``, ``title``,
    ``output_schema``, ``annotations``, ``tags``. Unknown keys are
    ignored so handlers can carry arbitrary auxiliary metadata.
    """
    out: dict[str, Any] = {}
    if "description" in schema:
        out["description"] = schema["description"]
    if "title" in schema:
        out["title"] = schema["title"]
    # Support both ``output_schema`` (snake) and ``outputSchema`` (camel).
    if "output_schema" in schema:
        out["output_schema"] = schema["output_schema"]
    elif "outputSchema" in schema:
        out["output_schema"] = schema["outputSchema"]
    if "annotations" in schema:
        out["annotations"] = schema["annotations"]
    if "tags" in schema:
        out["tags"] = schema["tags"]
    return out
