"""Tool registration: Tier 1 core profiling tools (8 tools).

Registers cognitive profiling, domain detection, and visualization tools.
"""

from __future__ import annotations

from fastmcp import FastMCP

from mcp_server.handlers import (
    detect_domain as detect_domain_handler,
)
from mcp_server.handlers import (
    explore_features,
    get_methodology_graph,
    list_domains,
    open_visualization,
    query_methodology,
    query_workflow_graph,
    rebuild_profiles,
    record_session_end,
)
from mcp_server.tool_error_handler import safe_handler
from mcp_server.handlers._tool_meta import tool_kwargs


def register(mcp: FastMCP) -> None:
    """Register all Tier 1 core profiling tools on the FastMCP instance."""
    _register_query_methodology(mcp)
    _register_detect_domain(mcp)
    _register_rebuild_profiles(mcp)
    _register_list_domains(mcp)
    _register_record_session_end(mcp)
    _register_get_methodology_graph(mcp)
    _register_query_workflow_graph(mcp)
    _register_open_visualization(mcp)
    _register_explore_features(mcp)


def _register_query_methodology(mcp: FastMCP) -> None:
    @mcp.tool(
        name="query_methodology",
        **tool_kwargs(query_methodology.schema),
    )
    async def tool_query_methodology(
        cwd: str | None = None,
        project: str | None = None,
        first_message: str | None = None,
    ) -> str:
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


def _register_detect_domain(mcp: FastMCP) -> None:
    @mcp.tool(
        name="detect_domain",
        **tool_kwargs(detect_domain_handler.schema),
    )
    async def tool_detect_domain(
        cwd: str | None = None,
        project: str | None = None,
        first_message: str | None = None,
    ) -> str:
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


def _register_rebuild_profiles(mcp: FastMCP) -> None:
    @mcp.tool(
        name="rebuild_profiles",
        **tool_kwargs(rebuild_profiles.schema),
    )
    async def tool_rebuild_profiles(
        domain: str | None = None,
        force: bool = False,
    ) -> str:
        """Full rescan of all session data to rebuild methodology profiles."""
        return await safe_handler(
            rebuild_profiles.handler,
            {
                "domain": domain,
                "force": force,
            },
            tool_name="rebuild_profiles",
        )


def _register_list_domains(mcp: FastMCP) -> None:
    @mcp.tool(
        name="list_domains",
        **tool_kwargs(list_domains.schema),
    )
    async def tool_list_domains() -> str:
        """Overview of all detected cognitive domains."""
        return await safe_handler(list_domains.handler, {}, tool_name="list_domains")


def _register_record_session_end(mcp: FastMCP) -> None:
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
    ) -> str:
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


def _register_get_methodology_graph(mcp: FastMCP) -> None:
    @mcp.tool(
        name="get_methodology_graph",
        **tool_kwargs(get_methodology_graph.schema),
    )
    async def tool_get_methodology_graph(
        domain: str | None = None,
    ) -> str:
        """Returns methodology map as graph data for 3D visualization."""
        return await safe_handler(
            get_methodology_graph.handler,
            {"domain": domain},
            tool_name="get_methodology_graph",
        )


def _register_query_workflow_graph(mcp: FastMCP) -> None:
    # Composition-root wrapper — schema surface, not a domain function.
    # §4.4 allows the param-count exception here (6 kwargs) because
    # these are the tool's advertised filter parameters; wrapping them
    # in a DTO would obscure the MCP schema the client reads.
    @mcp.tool(
        name="query_workflow_graph",
        **tool_kwargs(query_workflow_graph.schema),
    )
    async def tool_query_workflow_graph(
        node_kind: str | list[str] | None = None,
        edge_kind: str | list[str] | None = None,
        neighbour_of: str | None = None,
        depth: int | None = None,
        domain: str | None = None,
        limit_nodes: int | None = None,
    ) -> str:
        """Return a typed subgraph of the unified workflow graph."""
        return await safe_handler(
            query_workflow_graph.handler,
            {
                "node_kind": node_kind,
                "edge_kind": edge_kind,
                "neighbour_of": neighbour_of,
                "depth": depth,
                "domain": domain,
                "limit_nodes": limit_nodes,
            },
            tool_name="query_workflow_graph",
        )


def _register_open_visualization(mcp: FastMCP) -> None:
    @mcp.tool(
        name="open_visualization",
        **tool_kwargs(open_visualization.schema),
    )
    async def tool_open_visualization(
        domain: str | None = None,
    ) -> str:
        """Launch the 3D methodology constellation map in the browser."""
        return await safe_handler(
            open_visualization.handler,
            {"domain": domain},
            tool_name="open_visualization",
        )


def _register_explore_features(mcp: FastMCP) -> None:
    @mcp.tool(
        name="explore_features",
        **tool_kwargs(explore_features.schema),
    )
    async def tool_explore_features(
        mode: str,
        domain: str | None = None,
        compare_domain: str | None = None,
    ) -> str:
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
