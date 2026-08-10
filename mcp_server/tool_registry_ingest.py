"""Tool registration: ingestion tools.

ingest_codebase — pulls from ai-architect-mcp-codebase MCP
change_impact   — pulls from ai-architect-mcp-codebase MCP (ADR-0046)
ingest_prd      — pulls from prd-spec-generator MCP
ingest_findings — reads AP findings artifacts directly off disk (INC5.1)
ingest_document — reads .docx / Confluence export files off disk (issue #192)

Cortex consumes upstream artefacts; it does not drive those pipelines. The
MCP-calling tools (ingest_codebase, change_impact, ingest_prd) are
CONDITIONALLY registered: each only registers when its upstream MCP server
is reachable (see register()). ``ingest_findings`` and ``ingest_document``
are registered UNCONDITIONALLY: neither calls an upstream MCP server
(ingest_findings reads runs/<run_id>/ off disk per ADR-0052 D1;
ingest_document reads a .docx zip or a Confluence XHTML export off disk per
issue #192), so there is no upstream-availability flag to gate them on. On a
standalone install with no upstream configured, ingest_findings still
registers but returns {"ingested": false, "reason": "output_dir_not_resolved"}
until AP artifacts exist on disk; ingest_document works fully offline.
source: Anthropic MCP Directory submission decision 2026-06-19.
"""

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

    ``codebase`` registers ingest_codebase + change_impact (both consume the
    ai-architect-mcp-codebase ``codebase`` MCP). ``prd`` registers ingest_prd (it
    consumes the prd-spec-generator ``prd-gen`` MCP). The composition root
    (__main__) passes the real availability; both default True so any other
    caller keeps the full set. When a flag is False the corresponding tools are
    NOT advertised — the standalone tool set is exactly what works without an
    upstream. source: Anthropic MCP Directory submission decision 2026-06-19.

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

        No caps. Pulls every Function/Method/Struct/process the upstream
        graph holds, projects them all into Cortex memories + KG.

        ctx is injected by MCPServer when the client supports progress reporting.
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
        """Ingest a .docx or Confluence export into Cortex (issue #192)."""
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
