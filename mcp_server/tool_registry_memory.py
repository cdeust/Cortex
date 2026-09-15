"""Tool registration: Tier 1 memory read/write tools (remember, recall,
unified_search).

Maintenance/diagnostics tools (checkpoint, consolidate, narrative, etc.)
split out to tool_registry_memory_maintenance.py — see that module's
docstring and docs/module-inventory.md's 300-line file cap.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from mcp_server.handlers import recall, remember, unified_search
from mcp_server.infrastructure.memory_config import root_agent_topic
from mcp_server.tool_error_handler import safe_handler
from mcp_server.handlers._tool_meta import tool_kwargs


# Tool name → handler schema; __main__ hands the merged map to
# _tool_meta.apply_param_docs after registration.
SCHEMAS: dict[str, dict] = {
    "remember": remember.schema,
    "recall": recall.schema,
    "unified_search": unified_search.schema,
}


def register(mcp: MCPServer) -> None:
    """Register remember, recall, and unified_search on the MCPServer instance."""
    _register_remember(mcp)
    _register_recall(mcp)
    _register_unified_search(mcp)


def _register_remember(mcp: MCPServer) -> None:
    # source: ADR-0698

    if root_agent_topic() is not None:

        @mcp.tool(name="remember", **tool_kwargs(remember.schema))
        async def tool_remember_rooted(
            content: str,
            tags: list[str] | None = None,
            directory: str | None = None,
            domain: str | None = None,
            source: str | None = None,
            force: bool = False,
            supersedes_id: int | None = None,
            write_class: str | None = None,
            origin_tool: str | None = None,
            is_global: bool = False,
            created_at: str | None = None,
            initial_heat: float | None = None,
        ) -> dict[str, Any]:
            """Store a memory through the predictive coding write gate."""
            return await safe_handler(
                remember.handler,
                {
                    "content": content,
                    "tags": tags or [],
                    "directory": directory or "",
                    "domain": domain or "",
                    "source": source or "user",
                    "force": force,
                    "supersedes_id": supersedes_id,
                    "write_class": write_class,
                    "origin_tool": origin_tool,
                    "is_global": is_global,
                    "created_at": created_at,
                    "initial_heat": initial_heat,
                },
                tool_name="remember",
            )

        return

    @mcp.tool(
        name="remember",
        **tool_kwargs(remember.schema),
    )
    async def tool_remember(
        content: str,
        tags: list[str] | None = None,
        directory: str | None = None,
        domain: str | None = None,
        source: str | None = None,
        force: bool = False,
        agent_topic: str | None = None,
        supersedes_id: int | None = None,
        write_class: str | None = None,
        origin_tool: str | None = None,
        is_global: bool = False,
        created_at: str | None = None,
        initial_heat: float | None = None,
    ) -> dict[str, Any]:
        """Store a memory through the predictive coding write gate."""
        return await safe_handler(
            remember.handler,
            {
                "content": content,
                "tags": tags or [],
                "directory": directory or "",
                "domain": domain or "",
                "source": source or "user",
                "force": force,
                "agent_topic": agent_topic or "",
                "supersedes_id": supersedes_id,
                "write_class": write_class,
                "origin_tool": origin_tool,
                "is_global": is_global,
                "created_at": created_at,
                "initial_heat": initial_heat,
            },
            tool_name="remember",
        )


async def _do_recall(
    rooted: bool,
    query: str,
    domain: str | None,
    directory: str | None,
    max_results: int,
    min_heat: float,
    agent_topic: str | None,
    include_related: bool,
    format: str,
    memory_id: int | None,
    content_offset: int,
    project_root: str | None,
    exact_id: bool,
    include_low_signal: bool,
    cross_domain: bool,
    sa_mode: str,
    tags_any: list[str] | None,
    tags_all: list[str] | None,
) -> dict[str, Any]:
    """Shared recall dispatch; ``rooted`` forces agent_topic=None."""
    payload = {
        "query": query,
        "domain": domain,
        "directory": directory,
        "max_results": max_results,
        "min_heat": min_heat,
        "agent_topic": None if rooted else agent_topic,
        "include_related": include_related,
        "format": format,
        "memory_id": memory_id,
        "content_offset": content_offset,
        "project_root": project_root,
        "exact_id": exact_id,
        "include_low_signal": include_low_signal,
        "cross_domain": cross_domain,
        "sa_mode": sa_mode,
        "tags_any": tags_any or [],
        "tags_all": tags_all or [],
    }
    return await safe_handler(recall.handler, payload, tool_name="recall")


def _register_recall(mcp: MCPServer) -> None:
    # Connection-rooted scoping (see _register_remember): omit agent_topic
    # from the schema when rooted; the handler forces the root scope.
    if root_agent_topic() is not None:

        @mcp.tool(name="recall", **tool_kwargs(recall.schema))
        async def tool_recall_rooted(
            query: str,
            domain: str | None = None,
            directory: str | None = None,
            max_results: int = 10,
            min_heat: float = 0.05,
            include_related: bool = False,
            format: str = "json",
            memory_id: int | None = None,
            content_offset: int = 0,
            project_root: str | None = None,
            exact_id: bool = False,
            include_low_signal: bool = False,
            cross_domain: bool = False,
            sa_mode: str = "tail",
            tags_any: list[str] | None = None,
            tags_all: list[str] | None = None,
        ) -> dict[str, Any]:
            """Retrieve memories using multi-signal fusion."""
            return await _do_recall(
                True,
                query,
                domain,
                directory,
                max_results,
                min_heat,
                None,
                include_related,
                format,
                memory_id,
                content_offset,
                project_root,
                exact_id,
                include_low_signal,
                cross_domain,
                sa_mode,
                tags_any,
                tags_all,
            )

        return

    @mcp.tool(
        name="recall",
        **tool_kwargs(recall.schema),
    )
    async def tool_recall(
        query: str,
        domain: str | None = None,
        directory: str | None = None,
        max_results: int = 10,
        min_heat: float = 0.05,
        agent_topic: str | None = None,
        include_related: bool = False,
        format: str = "json",
        memory_id: int | None = None,
        content_offset: int = 0,
        project_root: str | None = None,
        exact_id: bool = False,
        include_low_signal: bool = False,
        cross_domain: bool = False,
        sa_mode: str = "tail",
        tags_any: list[str] | None = None,
        tags_all: list[str] | None = None,
    ) -> dict[str, Any]:
        """Retrieve memories using multi-signal fusion."""
        return await _do_recall(
            False,
            query,
            domain,
            directory,
            max_results,
            min_heat,
            agent_topic,
            include_related,
            format,
            memory_id,
            content_offset,
            project_root,
            exact_id,
            include_low_signal,
            cross_domain,
            sa_mode,
            tags_any,
            tags_all,
        )


def _register_unified_search(mcp: MCPServer) -> None:
    @mcp.tool(
        name="unified_search",
        **tool_kwargs(unified_search.schema),
    )
    async def tool_unified_search(
        query: str,
        domain: str | None = None,
        max_results: int = 10,
        k: int = 60,
        project_root: str | None = None,
        exact_id: bool = False,
        cross_domain: bool = False,
        sa_mode: str = "tail",
    ) -> dict[str, Any]:
        """Fuse Cortex recall with AP code search using reciprocal rank fusion."""
        # source: ADR-0698
        return await safe_handler(
            unified_search.handler,
            {
                "query": query,
                "domain": domain,
                "max_results": max_results,
                "k": k,
                "project_root": project_root,
                "exact_id": exact_id,
                "cross_domain": cross_domain,
                "sa_mode": sa_mode,
            },
            tool_name="unified_search",
        )
