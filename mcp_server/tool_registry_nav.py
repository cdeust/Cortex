"""Tool registration: Tier 2 navigation tools (5 tools).

Registers fractal navigation and knowledge graph traversal tools.
Tier 3 advanced tools are in tool_registry_advanced.py.
"""

from __future__ import annotations

from fastmcp import FastMCP

from mcp_server.handlers import (
    recall_hierarchical,
    drill_down,
    navigate_memory,
    get_causal_chain,
    detect_gaps,
)
from mcp_server.tool_error_handler import safe_handler


def register(mcp: FastMCP) -> None:
    """Register Tier 2 navigation tools."""
    _register_recall_hierarchical(mcp)
    _register_drill_down(mcp)
    _register_navigate_memory(mcp)
    _register_get_causal_chain(mcp)
    _register_detect_gaps(mcp)


def _register_recall_hierarchical(mcp: FastMCP) -> None:
    @mcp.tool(
        name="recall_hierarchical",
        description=recall_hierarchical.schema["description"],
    )
    async def tool_recall_hierarchical(
        query: str,
        domain: str | None = None,
        max_results: int = 10,
        min_heat: float = 0.05,
        cluster_threshold: float = 0.6,
    ) -> str:
        """Retrieve memories using fractal hierarchy."""
        return await safe_handler(
            recall_hierarchical.handler,
            {
                "query": query,
                "domain": domain,
                "max_results": max_results,
                "min_heat": min_heat,
                "cluster_threshold": cluster_threshold,
            },
        )


def _register_drill_down(mcp: FastMCP) -> None:
    @mcp.tool(
        name="drill_down",
        description=drill_down.schema["description"],
    )
    async def tool_drill_down(
        cluster_id: str,
        domain: str | None = None,
        min_heat: float = 0.05,
    ) -> str:
        """Navigate into a fractal memory cluster."""
        return await safe_handler(
            drill_down.handler,
            {
                "cluster_id": cluster_id,
                "domain": domain,
                "min_heat": min_heat,
            },
        )


def _register_navigate_memory(mcp: FastMCP) -> None:
    @mcp.tool(
        name="navigate_memory",
        description=navigate_memory.schema["description"],
    )
    async def tool_navigate_memory(
        memory_id: int,
        max_depth: int = 2,
        include_2d_map: bool = False,
        window_hours: float = 2.0,
    ) -> str:
        """Navigate memory space using Successor Representation."""
        return await safe_handler(
            navigate_memory.handler,
            {
                "memory_id": memory_id,
                "max_depth": max_depth,
                "include_2d_map": include_2d_map,
                "window_hours": window_hours,
            },
        )


def _register_get_causal_chain(mcp: FastMCP) -> None:
    @mcp.tool(
        name="get_causal_chain",
        description=get_causal_chain.schema["description"],
    )
    async def tool_get_causal_chain(
        entity_name: str | None = None,
        memory_id: int | None = None,
        relationship_types: list[str] | None = None,
        max_depth: int = 3,
        direction: str = "both",
    ) -> str:
        """Trace entity relationships through the knowledge graph."""
        return await safe_handler(
            get_causal_chain.handler,
            {
                "entity_name": entity_name,
                "memory_id": memory_id,
                "relationship_types": relationship_types,
                "max_depth": max_depth,
                "direction": direction,
            },
        )


def _register_detect_gaps(mcp: FastMCP) -> None:
    @mcp.tool(
        name="detect_gaps",
        description=detect_gaps.schema["description"],
    )
    async def tool_detect_gaps(
        domain: str | None = None,
        include_entity_gaps: bool = True,
        include_domain_gaps: bool = True,
        include_temporal_gaps: bool = True,
        stale_threshold_days: int = 30,
    ) -> str:
        """Identify knowledge gaps in the memory store."""
        return await safe_handler(
            detect_gaps.handler,
            {
                "domain": domain,
                "include_entity_gaps": include_entity_gaps,
                "include_domain_gaps": include_domain_gaps,
                "include_temporal_gaps": include_temporal_gaps,
                "stale_threshold_days": stale_threshold_days,
            },
        )
