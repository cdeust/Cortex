"""Tool registration: upstream-ingest tools (2 tools).

ingest_codebase — pulls from ai-automatised-pipeline MCP
ingest_prd      — pulls from prd-spec-generator MCP

Cortex consumes upstream artefacts; it does not drive those pipelines.
"""

from __future__ import annotations

from fastmcp import FastMCP

from mcp_server.handlers import change_impact, ingest_codebase, ingest_prd
from mcp_server.tool_error_handler import safe_handler


def register(mcp: FastMCP) -> None:
    _register_ingest_codebase(mcp)
    _register_ingest_prd(mcp)
    _register_change_impact(mcp)


def _register_ingest_codebase(mcp: FastMCP) -> None:
    @mcp.tool(
        name="ingest_codebase",
        description=ingest_codebase.schema["description"],
    )
    async def tool_ingest_codebase(
        project_path: str,
        output_dir: str | None = None,
        language: str = "auto",
        force_reindex: bool = False,
        top_symbols: int = 50,
        top_processes: int = 10,
    ) -> str:
        """Ingest upstream codebase analysis into Cortex."""
        return await safe_handler(
            ingest_codebase.handler,
            {
                "project_path": project_path,
                "output_dir": output_dir,
                "language": language,
                "force_reindex": force_reindex,
                "top_symbols": top_symbols,
                "top_processes": top_processes,
            },
            tool_name="ingest_codebase",
        )


def _register_change_impact(mcp: FastMCP) -> None:
    @mcp.tool(
        name="change_impact",
        description=change_impact.schema["description"],
    )
    async def tool_change_impact(
        base: str = "HEAD~1",
        head: str = "HEAD",
        expand_impact: bool = False,
        apply_heat_bump: bool = False,
    ) -> str:
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
        description=ingest_prd.schema["description"],
    )
    async def tool_ingest_prd(
        path: str | None = None,
        content: str | None = None,
        pipeline_id: str | None = None,
        title: str | None = None,
        validate: bool = False,
        domain: str | None = None,
    ) -> str:
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
