"""Tool registration: upstream-ingest tools (2 tools).

ingest_codebase — pulls from ai-automatised-pipeline MCP
ingest_prd      — pulls from prd-spec-generator MCP

Cortex consumes upstream artefacts; it does not drive those pipelines.
"""

from __future__ import annotations

import asyncio
import functools

from fastmcp import Context, FastMCP

from mcp_server.handlers import change_impact, ingest_codebase, ingest_prd
from mcp_server.mcp_progress import McpProgress
from mcp_server.shared.progress import NullProgress
from mcp_server.tool_error_handler import safe_handler
from mcp_server.handlers._tool_meta import tool_kwargs


def register(mcp: FastMCP) -> None:
    _register_ingest_codebase(mcp)
    _register_ingest_prd(mcp)
    _register_change_impact(mcp)


def _register_ingest_codebase(mcp: FastMCP) -> None:
    @mcp.tool(
        name="ingest_codebase",
        **tool_kwargs(ingest_codebase.schema),
    )
    async def tool_ingest_codebase(
        project_path: str,
        output_dir: str | None = None,
        language: str = "auto",
        force_reindex: bool = False,
        ctx: Context | None = None,
    ) -> dict:
        """Ingest upstream codebase analysis into Cortex.

        No caps. Pulls every Function/Method/Struct/process the upstream
        graph holds, projects them all into Cortex memories + KG.

        ctx is injected by FastMCP when the client supports progress reporting.
        Progress dispatches to the main loop via run_coroutine_threadsafe because
        the handler body runs on a worker thread (asyncio.to_thread in safe_handler).
        """
        # Build the progress reporter bound to THIS event loop before handing
        # off to the worker thread (asyncio.to_thread). The worker thread must
        # NOT call get_running_loop() — it has its own fresh loop.
        progress: McpProgress | NullProgress
        if ctx is not None:
            progress = McpProgress(ctx, asyncio.get_running_loop())
        else:
            progress = NullProgress()
        fn = functools.partial(ingest_codebase.handler, progress=progress)
        return await safe_handler(
            fn,
            {
                "project_path": project_path,
                "output_dir": output_dir,
                "language": language,
                "force_reindex": force_reindex,
                "top_symbols": None,
                "top_processes": None,
            },
            tool_name="ingest_codebase",
        )


def _register_change_impact(mcp: FastMCP) -> None:
    @mcp.tool(
        name="change_impact",
        **tool_kwargs(change_impact.schema),
    )
    async def tool_change_impact(
        base: str = "HEAD~1",
        head: str = "HEAD",
        expand_impact: bool = False,
        apply_heat_bump: bool = False,
    ) -> dict:
        """Report memories affected by a commit's code changes (ADR-0046 P4)."""
        return await safe_handler(
            change_impact.handler,
            {
                "base": base,
                "head": head,
                "expand_impact": expand_impact,
                "apply_heat_bump": apply_heat_bump,
            },
            tool_name="change_impact",
        )


def _register_ingest_prd(mcp: FastMCP) -> None:
    @mcp.tool(
        name="ingest_prd",
        **tool_kwargs(ingest_prd.schema),
    )
    async def tool_ingest_prd(
        path: str | None = None,
        content: str | None = None,
        pipeline_id: str | None = None,
        title: str | None = None,
        validate: bool = False,
        domain: str | None = None,
    ) -> dict:
        """Ingest a PRD document into Cortex."""
        return await safe_handler(
            ingest_prd.handler,
            {
                "path": path,
                "content": content,
                "pipeline_id": pipeline_id,
                "title": title,
                "validate": validate,
                "domain": domain,
            },
            tool_name="ingest_prd",
        )
