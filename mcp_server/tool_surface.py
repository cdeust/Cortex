"""What this tree registers: the standalone tools and the gated ones.

The number appears in a test, in nine documents, in the docker-smoke floor
and in the host-contract verifier, and every one of them used to carry its
own copy. One copy went stale: `scripts/verify_mcp_hosts.py` held 52 while
the surface moved to 54 (ADR-1066), which nothing noticed until the count
reached 57 and broke its ceiling (issue #597).

This module is the one place that counts, read from the registries rather
than stated. It imports the registry modules only, never the server, so a
caller pays no MCP startup for a count.

source: ADR-1077"""

from __future__ import annotations

from mcp_server import (
    tool_registry_advanced,
    tool_registry_core,
    tool_registry_ingest,
    tool_registry_manage,
    tool_registry_memory,
    tool_registry_memory_maintenance,
    tool_registry_nav,
    tool_registry_predictions,
    tool_registry_wiki,
    tool_registry_wiki_drafts,
)

# The three tools that register only when their upstream MCP server is
# configured; every advertised tool works without one (ADR-0093).
UPSTREAM_TOOL_NAMES: frozenset[str] = frozenset(
    {"ingest_codebase", "change_impact", "ingest_prd"}
)

_STANDALONE_REGISTRIES = (
    tool_registry_core,
    tool_registry_memory,
    tool_registry_memory_maintenance,
    tool_registry_manage,
    tool_registry_nav,
    tool_registry_predictions,
    tool_registry_advanced,
    tool_registry_wiki,
    tool_registry_wiki_drafts,
)


def standalone_tool_names() -> frozenset[str]:
    """Every tool name that registers without an upstream MCP server."""
    names: set[str] = set()
    for registry in _STANDALONE_REGISTRIES:
        names.update(registry.SCHEMAS)
    names.update(set(tool_registry_ingest.SCHEMAS) - UPSTREAM_TOOL_NAMES)
    return frozenset(names)
