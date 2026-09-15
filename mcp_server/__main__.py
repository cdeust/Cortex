"""Bootstrap entry point for the methodology-agent MCP server.

source: ADR-0093

Usage:
    python -m mcp_server
"""

from __future__ import annotations

import signal
import sys

# source: ADR-0093


try:  # pragma: no cover — defensive; sentence-transformers is mandatory
    # source: ADR-0093

    import scipy.linalg  # noqa: F401
    import scipy.special  # noqa: F401
    import sklearn.utils  # noqa: F401
    import sklearn.utils.validation  # noqa: F401
except Exception as _preload_exc:  # noqa: BLE001 — source: ADR-0093
    # source: ADR-0093

    print(
        f"[cortex] scipy/sklearn preload failed (startup continues): {_preload_exc}",
        file=sys.stderr,
    )

import anyio
from mcp.server.mcpserver import MCPServer

from mcp_server import (
    mcp_prompts,
    tool_profiles,
    tool_registry_advanced,
    tool_registry_core,
    tool_registry_ingest,
    tool_registry_manage,
    tool_registry_memory,
    tool_registry_memory_maintenance,
    tool_registry_nav,
    tool_registry_wiki,
)
from mcp_server.composition_root import wire_composition_root
from mcp_server.core import telemetry
from mcp_server.telemetry_middleware import TelemetryMiddleware
from mcp_server.tool_profile_middleware import ToolProfileMiddleware
from mcp_server.core.wiki_classifier import configure_user_rules_provider
from mcp_server.handlers._tool_meta import apply_output_schemas, apply_param_docs
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.mcp_client_pool import close_all
from mcp_server.infrastructure.otel_exporter import build_otel_exporter
from mcp_server.infrastructure.upstream_availability import (
    codebase_upstream_available,
    prd_upstream_available,
)
from mcp_server.infrastructure.wiki_schema_reader import load_registry

# source: ADR-0093


wire_composition_root()
configure_user_rules_provider(lambda: load_registry(WIKI_ROOT).rules)

# source: ADR-0093


telemetry.set_exporter(build_otel_exporter())

# source: ADR-0093


ACTIVE_PROFILE = tool_profiles.resolve()

# source: ADR-0093


mcp = MCPServer(
    name="methodology-agent",
    version="1.0.0",
    # source: ADR-0093
    instructions=tool_profiles.instructions(ACTIVE_PROFILE),
    middleware=[TelemetryMiddleware(), ToolProfileMiddleware(ACTIVE_PROFILE)],
)

# ── Tool Registration ──────────────────────────────────────────────────────


def merged_schemas() -> dict[str, dict]:
    """The tool-name → handler-schema map, merged across every registry.

    source: ADR-0093"""
    return {
        **tool_registry_core.SCHEMAS,
        **tool_registry_memory.SCHEMAS,
        **tool_registry_memory_maintenance.SCHEMAS,
        **tool_registry_manage.SCHEMAS,
        **tool_registry_nav.SCHEMAS,
        **tool_registry_advanced.SCHEMAS,
        **tool_registry_wiki.SCHEMAS,
        **tool_registry_ingest.SCHEMAS,
    }


def register_all(mcp: MCPServer, *, codebase: bool, prd: bool) -> None:
    """Wire every tool registry onto ``mcp``.

    source: ADR-0093"""
    tool_registry_core.register(mcp)
    tool_registry_memory.register(mcp)
    tool_registry_memory_maintenance.register(mcp)
    tool_registry_manage.register(mcp)
    tool_registry_nav.register(mcp)
    tool_registry_advanced.register(mcp)
    tool_registry_wiki.register(mcp)
    tool_registry_ingest.register(mcp, codebase=codebase, prd=prd)
    # source: ADR-0093

    apply_param_docs(mcp, merged_schemas())
    apply_output_schemas(mcp, merged_schemas())


register_all(
    mcp,
    codebase=codebase_upstream_available(),
    prd=prd_upstream_available(),
)

# source: ADR-0093


mcp_prompts.register_prompts(mcp, merged_schemas())

# source: ADR-0093


# ── Lifecycle ──────────────────────────────────────────────────────────────


def _shutdown(sig=None, frame=None) -> None:
    close_all()
    sys.exit(0)


def main() -> None:
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    # source: ADR-0093

    anyio.run(mcp.run_stdio_async)


if __name__ == "__main__":
    main()
