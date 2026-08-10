"""Tool registration: Tier 1 core profiling tools (6 tools).

Registers cognitive profiling and domain detection tools. The visualization
tools (get_methodology_graph, open_visualization) were extracted to the
standalone cortex-viz MCP.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from mcp_server.handlers import (
    detect_domain as detect_domain_handler,
)
from mcp_server.handlers import (
    explore_features,
    list_domains,
    query_methodology,
    rebuild_profiles,
    record_session_end,
)
from mcp_server.tool_error_handler import safe_handler
from mcp_server.handlers._tool_meta import tool_kwargs


# Tool name → handler schema; __main__ hands the merged map to
# _tool_meta.apply_param_docs after registration.
SCHEMAS: dict[str, dict] = {
    "detect_domain": detect_domain_handler.schema,
    "explore_features": explore_features.schema,
    "list_domains": list_domains.schema,
    "query_methodology": query_methodology.schema,
    "rebuild_profiles": rebuild_profiles.schema,
    "record_session_end": record_session_end.schema,
}


def register(mcp: MCPServer) -> None:
    """Register all Tier 1 core profiling tools on the MCPServer instance."""
    _register_query_methodology(mcp)
    _register_detect_domain(mcp)
    _register_rebuild_profiles(mcp)
    _register_list_domains(mcp)
    _register_record_session_end(mcp)
    _register_explore_features(mcp)


def _register_query_methodology(mcp: MCPServer) -> None:
    @mcp.tool(
        name="query_methodology",
        **tool_kwargs(query_methodology.schema),
    )
    async def tool_query_methodology(
        cwd: str | None = None,
        project: str | None = None,
        first_message: str | None = None,
    ) -> dict[str, Any]:
        """Returns cognitive profile for the current domain."""
        return await safe_handler(
            query_methodology.handler,
            {
                "cwd": cwd,
                "project": project,
                "first_message": first_message,
            },
            tool_name="query_methodology",
        )


def _register_detect_domain(mcp: MCPServer) -> None:
    @mcp.tool(
        name="detect_domain",
        **tool_kwargs(detect_domain_handler.schema),
    )
    async def tool_detect_domain(
        cwd: str | None = None,
        project: str | None = None,
        first_message: str | None = None,
    ) -> dict[str, Any]:
        """Lightweight domain classification."""
        return await safe_handler(
            detect_domain_handler.handler,
            {
                "cwd": cwd,
                "project": project,
                "first_message": first_message,
            },
            tool_name="detect_domain",
        )


def _register_rebuild_profiles(mcp: MCPServer) -> None:
    @mcp.tool(
        name="rebuild_profiles",
        **tool_kwargs(rebuild_profiles.schema),
    )
    async def tool_rebuild_profiles(
        domain: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Full rescan of all session data to rebuild methodology profiles."""
        return await safe_handler(
            rebuild_profiles.handler,
            {
                "domain": domain,
                "force": force,
            },
            tool_name="rebuild_profiles",
        )


def _register_list_domains(mcp: MCPServer) -> None:
    @mcp.tool(
        name="list_domains",
        **tool_kwargs(list_domains.schema),
    )
    async def tool_list_domains() -> dict[str, Any]:
        """Overview of all detected cognitive domains."""
        return await safe_handler(list_domains.handler, {}, tool_name="list_domains")


def _register_record_session_end(mcp: MCPServer) -> None:
    @mcp.tool(
        name="record_session_end",
        **tool_kwargs(record_session_end.schema),
    )
    async def tool_record_session_end(
        session_id: str,
        domain: str | None = None,
        tools_used: list[str] | None = None,
        duration: float | None = None,
        turn_count: int | None = None,
        keywords: list[str] | None = None,
        cwd: str | None = None,
        project: str | None = None,
    ) -> dict[str, Any]:
        """Incremental profile update after a session ends."""
        return await safe_handler(
            record_session_end.handler,
            {
                "session_id": session_id,
                "domain": domain,
                "tools_used": tools_used,
                "duration": duration,
                "turn_count": turn_count,
                "keywords": keywords,
                "cwd": cwd,
                "project": project,
            },
            tool_name="record_session_end",
        )


def _register_explore_features(mcp: MCPServer) -> None:
    @mcp.tool(
        name="explore_features",
        **tool_kwargs(explore_features.schema),
    )
    async def tool_explore_features(
        mode: str,
        domain: str | None = None,
        compare_domain: str | None = None,
    ) -> dict[str, Any]:
        """Explore interpretability features."""
        return await safe_handler(
            explore_features.handler,
            {
                "mode": mode,
                "domain": domain,
                "compare_domain": compare_domain,
            },
            tool_name="explore_features",
        )
