"""Tool registration: Tier 2 navigation tools (7 tools).

Registers fractal navigation, knowledge graph traversal, and injection
provenance (blame path) tools.
Tier 3 advanced tools are in tool_registry_advanced.py.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from mcp_server.handlers import (
    detect_gaps,
    drill_down,
    get_causal_chain,
    navigate_memory,
    recall_hierarchical,
    recall_skills,
    why,
)
from mcp_server.tool_error_handler import safe_handler
from mcp_server.handlers._tool_meta import tool_kwargs


# Tool name → handler schema; __main__ hands the merged map to
# _tool_meta.apply_param_docs after registration.
SCHEMAS: dict[str, dict] = {
    "detect_gaps": detect_gaps.schema,
    "drill_down": drill_down.schema,
    "get_causal_chain": get_causal_chain.schema,
    "navigate_memory": navigate_memory.schema,
    "recall_hierarchical": recall_hierarchical.schema,
    "recall_skills": recall_skills.schema,
    "why": why.schema,
}


def register(mcp: MCPServer) -> None:
    """Register Tier 2 navigation tools."""
    _register_recall_hierarchical(mcp)
    _register_drill_down(mcp)
    _register_navigate_memory(mcp)
    _register_get_causal_chain(mcp)
    _register_detect_gaps(mcp)
    _register_recall_skills(mcp)
    _register_why(mcp)


def _register_recall_hierarchical(mcp: MCPServer) -> None:
    @mcp.tool(
        name="recall_hierarchical",
        **tool_kwargs(recall_hierarchical.schema),
    )
    async def tool_recall_hierarchical(
        query: str,
        domain: str | None = None,
        max_results: int = 10,
        min_heat: float = 0.05,
        cluster_threshold: float = 0.6,
    ) -> dict[str, Any]:
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
            tool_name="recall_hierarchical",
        )


def _register_drill_down(mcp: MCPServer) -> None:
    @mcp.tool(
        name="drill_down",
        **tool_kwargs(drill_down.schema),
    )
    async def tool_drill_down(
        cluster_id: str,
        domain: str | None = None,
        min_heat: float = 0.05,
    ) -> dict[str, Any]:
        """Navigate into a fractal memory cluster."""
        return await safe_handler(
            drill_down.handler,
            {
                "cluster_id": cluster_id,
                "domain": domain,
                "min_heat": min_heat,
            },
            tool_name="drill_down",
        )


def _register_navigate_memory(mcp: MCPServer) -> None:
    @mcp.tool(
        name="navigate_memory",
        **tool_kwargs(navigate_memory.schema),
    )
    async def tool_navigate_memory(
        memory_id: int,
        max_depth: int = 2,
        include_2d_map: bool = False,
        window_hours: float = 2.0,
    ) -> dict[str, Any]:
        """Navigate memory space using Successor Representation."""
        return await safe_handler(
            navigate_memory.handler,
            {
                "memory_id": memory_id,
                "max_depth": max_depth,
                "include_2d_map": include_2d_map,
                "window_hours": window_hours,
            },
            tool_name="navigate_memory",
        )


def _register_get_causal_chain(mcp: MCPServer) -> None:
    @mcp.tool(
        name="get_causal_chain",
        **tool_kwargs(get_causal_chain.schema),
    )
    async def tool_get_causal_chain(
        entity_name: str | None = None,
        memory_id: int | None = None,
        relationship_types: list[str] | None = None,
        max_depth: int = 3,
        direction: str = "both",
    ) -> dict[str, Any]:
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
            tool_name="get_causal_chain",
        )


def _register_detect_gaps(mcp: MCPServer) -> None:
    @mcp.tool(
        name="detect_gaps",
        **tool_kwargs(detect_gaps.schema),
    )
    async def tool_detect_gaps(
        domain: str | None = None,
        include_entity_gaps: bool = True,
        include_domain_gaps: bool = True,
        include_temporal_gaps: bool = True,
        stale_threshold_days: int = 30,
    ) -> dict[str, Any]:
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
            tool_name="detect_gaps",
        )


def _register_recall_skills(mcp: MCPServer) -> None:
    @mcp.tool(
        name="recall_skills",
        **tool_kwargs(recall_skills.schema),
    )
    async def tool_recall_skills(
        domain: str | None = None,
        cwd: str | None = None,
        recent_tools: list[str] | None = None,
        top_k: int = 5,
        min_proficiency: float = 0.5,
    ) -> dict[str, Any]:
        """Retrieve procedural skills for the current situation."""
        return await safe_handler(
            recall_skills.handler,
            {
                "domain": domain,
                "cwd": cwd,
                "recent_tools": recent_tools,
                "top_k": top_k,
                "min_proficiency": min_proficiency,
            },
            tool_name="recall_skills",
        )


def _register_why(mcp: MCPServer) -> None:
    @mcp.tool(
        name="why",
        **tool_kwargs(why.schema),
    )
    async def tool_why(receipt_ids: list[int]) -> dict[str, Any]:
        """Resolve ⟦rcpt:id⟧ injection receipts into presence-in-context evidence."""
        return await safe_handler(
            why.handler,
            {"receipt_ids": receipt_ids},
            tool_name="why",
        )
