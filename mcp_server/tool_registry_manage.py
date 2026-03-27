"""Tool registration: Tier 1 memory management tools (6 tools).

Registers forget, validate, rate, seed, anchor, and backfill tools.
"""

from __future__ import annotations

from fastmcp import FastMCP

from mcp_server.handlers import (
    forget,
    validate_memory,
    rate_memory,
    seed_project,
    anchor,
    backfill_memories,
)
from mcp_server.tool_error_handler import safe_handler


def register(mcp: FastMCP) -> None:
    """Register Tier 1 memory management tools on the FastMCP instance."""
    _register_forget(mcp)
    _register_validate_memory(mcp)
    _register_rate_memory(mcp)
    _register_seed_project(mcp)
    _register_anchor(mcp)
    _register_backfill_memories(mcp)


def _register_forget(mcp: FastMCP) -> None:
    @mcp.tool(
        name="forget",
        description=forget.schema["description"],
    )
    async def tool_forget(
        memory_id: int,
        soft: bool = False,
        force: bool = False,
    ) -> str:
        """Delete or soft-delete a memory by ID."""
        return await safe_handler(forget.handler, {
            "memory_id": memory_id, "soft": soft, "force": force,
        })


def _register_validate_memory(mcp: FastMCP) -> None:
    @mcp.tool(
        name="validate_memory",
        description=validate_memory.schema["description"],
    )
    async def tool_validate_memory(
        memory_id: int | None = None,
        domain: str | None = None,
        directory: str | None = None,
        base_dir: str | None = None,
        staleness_threshold: float = 0.5,
        dry_run: bool = False,
    ) -> str:
        """Validate memories against current filesystem state."""
        return await safe_handler(validate_memory.handler, {
            "memory_id": memory_id,
            "domain": domain,
            "directory": directory,
            "base_dir": base_dir or "",
            "staleness_threshold": staleness_threshold,
            "dry_run": dry_run,
        })


def _register_rate_memory(mcp: FastMCP) -> None:
    @mcp.tool(
        name="rate_memory",
        description=rate_memory.schema["description"],
    )
    async def tool_rate_memory(
        memory_id: int,
        useful: bool,
    ) -> str:
        """Rate a memory as useful or not to update metamemory confidence."""
        return await safe_handler(rate_memory.handler, {
            "memory_id": memory_id, "useful": useful,
        })


def _register_seed_project(mcp: FastMCP) -> None:
    @mcp.tool(
        name="seed_project",
        description=seed_project.schema["description"],
    )
    async def tool_seed_project(
        directory: str | None = None,
        domain: str | None = None,
        max_file_size_kb: int = 64,
        dry_run: bool = False,
    ) -> str:
        """Bootstrap memory from an existing codebase."""
        return await safe_handler(seed_project.handler, {
            "directory": directory or "",
            "domain": domain or "",
            "max_file_size_kb": max_file_size_kb,
            "dry_run": dry_run,
        })


def _register_anchor(mcp: FastMCP) -> None:
    @mcp.tool(
        name="anchor",
        description=anchor.schema["description"],
    )
    async def tool_anchor(
        memory_id: int,
        reason: str | None = None,
    ) -> str:
        """Mark a memory as compaction-resistant (heat=1.0)."""
        return await safe_handler(anchor.handler, {
            "memory_id": memory_id, "reason": reason or "",
        })


def _register_backfill_memories(mcp: FastMCP) -> None:
    @mcp.tool(
        name="backfill_memories",
        description=backfill_memories.schema["description"],
    )
    async def tool_backfill_memories(
        project: str | None = None,
        max_files: int = 20,
        min_importance: float = 0.35,
        dry_run: bool = False,
        force_reprocess: bool = False,
    ) -> str:
        """Auto-import prior Claude Code conversations into memory."""
        return await safe_handler(backfill_memories.handler, {
            "project": project or "",
            "max_files": max_files,
            "min_importance": min_importance,
            "dry_run": dry_run,
            "force_reprocess": force_reprocess,
        })
