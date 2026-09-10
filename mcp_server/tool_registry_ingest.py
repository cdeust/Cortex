"""Tool registration: ingestion tools.

source: ADR-0696"""

from __future__ import annotations

import asyncio
import functools

from typing import Any

from mcp.server.mcpserver import Context, MCPServer

from mcp_server.handlers import (
    change_impact,
    ingest_codebase,
    ingest_document,
    ingest_findings,
    ingest_prd,
)
from mcp_server.mcp_progress import McpProgress
from mcp_server.shared.progress import NullProgress
from mcp_server.tool_error_handler import safe_handler
from mcp_server.handlers._tool_meta import tool_kwargs


# Tool name → handler schema; __main__ hands the merged map to
# _tool_meta.apply_param_docs after registration. Unregistered upstream
# tools are skipped there (the merge walks registered tools only).
SCHEMAS: dict[str, dict] = {
    "ingest_codebase": ingest_codebase.schema,
    "change_impact": change_impact.schema,
    "ingest_prd": ingest_prd.schema,
    "ingest_findings": ingest_findings.schema,
    "ingest_document": ingest_document.schema,
}


def register(mcp: MCPServer, *, codebase: bool = True, prd: bool = True) -> None:
    """Register the upstream-integration tools, gated by upstream availability.

    source: ADR-0696

    ``ingest_findings`` and ``ingest_document`` always register (see module
    docstring — both file-only, no upstream MCP dependency to gate on).
    """
    if codebase:
        _register_ingest_codebase(mcp)
        _register_change_impact(mcp)
    if prd:
        _register_ingest_prd(mcp)
    _register_ingest_findings(mcp)
    _register_ingest_document(mcp)


def _register_ingest_codebase(mcp: MCPServer) -> None:
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
    ) -> dict[str, Any]:
        """Ingest upstream codebase analysis into Cortex.

        Pulls every Function/Method/Struct/process into Cortex memories and
        knowledge-graph records without caps. ``ctx`` receives progress reports
        when the MCP client supports them."""
        # source: ADR-0696
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


def _register_change_impact(mcp: MCPServer) -> None:
    @mcp.tool(
        name="change_impact",
        **tool_kwargs(change_impact.schema),
    )
    async def tool_change_impact(
        base: str = "HEAD~1",
        head: str = "HEAD",
        expand_impact: bool = False,
        apply_heat_bump: bool = False,
    ) -> dict[str, Any]:
        """Report memories affected by a commit's code changes."""
        # source: ADR-0696
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


def _register_ingest_prd(mcp: MCPServer) -> None:
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
    ) -> dict[str, Any]:
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


def _register_ingest_findings(mcp: MCPServer) -> None:
    @mcp.tool(
        name="ingest_findings",
        **tool_kwargs(ingest_findings.schema),
    )
    async def tool_ingest_findings(
        run_id: str,
        output_dir: str | None = None,
        graph_key: str | None = None,
    ) -> dict[str, Any]:
        """Ingest an AP findings run (runs/<run_id>/) into Cortex."""
        return await safe_handler(
            ingest_findings.handler,
            {
                "run_id": run_id,
                "output_dir": output_dir,
                "graph_key": graph_key,
            },
            tool_name="ingest_findings",
        )


def _register_ingest_document(mcp: MCPServer) -> None:
    @mcp.tool(
        name="ingest_document",
        **tool_kwargs(ingest_document.schema),
    )
    async def tool_ingest_document(
        path: str,
        format: str = "auto",
        title: str | None = None,
        domain: str | None = None,
    ) -> dict[str, Any]:
        """Ingest a .docx or Confluence export into Cortex."""
        # source: ADR-0696
        return await safe_handler(
            ingest_document.handler,
            {
                "path": path,
                "format": format,
                "title": title,
                "domain": domain,
            },
            tool_name="ingest_document",
        )
