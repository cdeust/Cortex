"""Tool registration: Tier 1 core profiling tools (9 tools).

Registers cognitive profiling, domain detection, and visualization tools.
"""

from __future__ import annotations

from fastmcp import FastMCP

from mcp_server.handlers import (
    query_methodology,
    detect_domain as detect_domain_handler,
    rebuild_profiles,
    list_domains,
    record_session_end,
    get_methodology_graph,
    open_visualization,
    explore_features,
    run_pipeline,
)
from mcp_server.tool_error_handler import safe_handler


def register(mcp: FastMCP) -> None:
    """Register all Tier 1 core profiling tools on the FastMCP instance."""
    _register_query_methodology(mcp)
    _register_detect_domain(mcp)
    _register_rebuild_profiles(mcp)
    _register_list_domains(mcp)
    _register_record_session_end(mcp)
    _register_get_methodology_graph(mcp)
    _register_open_visualization(mcp)
    _register_explore_features(mcp)
    _register_run_pipeline(mcp)


def _register_query_methodology(mcp: FastMCP) -> None:
    @mcp.tool(
        name="query_methodology",
        description=query_methodology.schema["description"],
    )
    async def tool_query_methodology(
        cwd: str | None = None,
        project: str | None = None,
        first_message: str | None = None,
    ) -> str:
        """Returns cognitive profile for the current domain."""
        return await safe_handler(query_methodology.handler, {
            "cwd": cwd, "project": project, "first_message": first_message,
        })


def _register_detect_domain(mcp: FastMCP) -> None:
    @mcp.tool(
        name="detect_domain",
        description=detect_domain_handler.schema["description"],
    )
    async def tool_detect_domain(
        cwd: str | None = None,
        project: str | None = None,
        first_message: str | None = None,
    ) -> str:
        """Lightweight domain classification."""
        return await safe_handler(detect_domain_handler.handler, {
            "cwd": cwd, "project": project, "first_message": first_message,
        })


def _register_rebuild_profiles(mcp: FastMCP) -> None:
    @mcp.tool(
        name="rebuild_profiles",
        description=rebuild_profiles.schema["description"],
    )
    async def tool_rebuild_profiles(
        domain: str | None = None,
        force: bool = False,
    ) -> str:
        """Full rescan of all session data to rebuild methodology profiles."""
        return await safe_handler(rebuild_profiles.handler, {
            "domain": domain, "force": force,
        })


def _register_list_domains(mcp: FastMCP) -> None:
    @mcp.tool(
        name="list_domains",
        description=list_domains.schema["description"],
    )
    async def tool_list_domains() -> str:
        """Overview of all detected cognitive domains."""
        return await safe_handler(list_domains.handler, {})


def _register_record_session_end(mcp: FastMCP) -> None:
    @mcp.tool(
        name="record_session_end",
        description=record_session_end.schema["description"],
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
        return await safe_handler(record_session_end.handler, {
            "session_id": session_id,
            "domain": domain,
            "tools_used": tools_used,
            "duration": duration,
            "turn_count": turn_count,
            "keywords": keywords,
            "cwd": cwd,
            "project": project,
        })


def _register_get_methodology_graph(mcp: FastMCP) -> None:
    @mcp.tool(
        name="get_methodology_graph",
        description=get_methodology_graph.schema["description"],
    )
    async def tool_get_methodology_graph(
        domain: str | None = None,
    ) -> str:
        """Returns methodology map as graph data for 3D visualization."""
        return await safe_handler(get_methodology_graph.handler, {"domain": domain})


def _register_open_visualization(mcp: FastMCP) -> None:
    @mcp.tool(
        name="open_visualization",
        description=open_visualization.schema["description"],
    )
    async def tool_open_visualization(
        domain: str | None = None,
    ) -> str:
        """Launch the 3D methodology constellation map in the browser."""
        return await safe_handler(open_visualization.handler, {"domain": domain})


def _register_explore_features(mcp: FastMCP) -> None:
    @mcp.tool(
        name="explore_features",
        description=explore_features.schema["description"],
    )
    async def tool_explore_features(
        mode: str,
        domain: str | None = None,
        compare_domain: str | None = None,
    ) -> str:
        """Explore interpretability features."""
        return await safe_handler(explore_features.handler, {
            "mode": mode, "domain": domain, "compare_domain": compare_domain,
        })


def _register_run_pipeline(mcp: FastMCP) -> None:
    @mcp.tool(
        name="run_pipeline",
        description=run_pipeline.schema["description"],
    )
    async def tool_run_pipeline(
        codebase_path: str,
        task_path: str,
        context_path: str | None = None,
        github_repo: str | None = None,
        server: str | None = None,
        max_findings: int = 5,
    ) -> str:
        """Drive the ai-architect pipeline end-to-end."""
        return await safe_handler(run_pipeline.handler, {
            "codebase_path": codebase_path,
            "task_path": task_path,
            "context_path": context_path,
            "github_repo": github_repo,
            "server": server,
            "max_findings": max_findings,
        })
