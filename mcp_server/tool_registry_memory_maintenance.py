"""Tool registration: Tier 1 memory maintenance/diagnostics tools.

Split out of tool_registry_memory.py (which keeps remember, recall, and
unified_search) per docs/module-inventory.md's 300-line file cap —
issue #559 grew tool_registry_memory.py's wrapper signatures enough to
exceed it. Registers memory_stats, checkpoint, narrative, consolidate,
import_sessions, get_telemetry, and get_grooming_health — none of which
has a caller outside this module's own ``register()`` (verified by
grep before the split), so moving them carries no cross-module
reference to update.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from mcp_server.handlers import (
    checkpoint,
    consolidate,
    get_grooming_health,
    get_telemetry,
    import_sessions,
    memory_stats,
    narrative,
)
from mcp_server.tool_error_handler import safe_handler
from mcp_server.handlers._tool_meta import tool_kwargs


# Tool name → handler schema; __main__ hands the merged map to
# _tool_meta.apply_param_docs after registration.
SCHEMAS: dict[str, dict] = {
    "memory_stats": memory_stats.schema,
    "checkpoint": checkpoint.schema,
    "narrative": narrative.schema,
    "consolidate": consolidate.schema,
    "import_sessions": import_sessions.schema,
    "get_telemetry": get_telemetry.schema,
    "get_grooming_health": get_grooming_health.schema,
}


def register(mcp: MCPServer) -> None:
    """Register Tier 1 memory maintenance/diagnostics tools."""
    _register_memory_stats(mcp)
    _register_checkpoint(mcp)
    _register_narrative(mcp)
    _register_consolidate(mcp)
    _register_import_sessions(mcp)
    _register_get_telemetry(mcp)
    _register_get_grooming_health(mcp)


def _register_memory_stats(mcp: MCPServer) -> None:
    @mcp.tool(
        name="memory_stats",
        **tool_kwargs(memory_stats.schema),
    )
    async def tool_memory_stats() -> dict[str, Any]:
        """Memory system diagnostics."""
        return await safe_handler(memory_stats.handler, {}, tool_name="memory_stats")


def _register_checkpoint(mcp: MCPServer) -> None:
    @mcp.tool(
        name="checkpoint",
        **tool_kwargs(checkpoint.schema),
    )
    async def tool_checkpoint(
        action: str,
        directory: str | None = None,
        current_task: str | None = None,
        files_being_edited: list[str] | None = None,
        key_decisions: list[str] | None = None,
        open_questions: list[str] | None = None,
        next_steps: list[str] | None = None,
        active_errors: list[str] | None = None,
        custom_context: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Save or restore working state for hippocampal replay."""
        return await safe_handler(
            checkpoint.handler,
            {
                "action": action,
                "directory": directory or "",
                "current_task": current_task or "",
                "files_being_edited": files_being_edited or [],
                "key_decisions": key_decisions or [],
                "open_questions": open_questions or [],
                "next_steps": next_steps or [],
                "active_errors": active_errors or [],
                "custom_context": custom_context or "",
                "session_id": session_id or "default",
            },
            tool_name="checkpoint",
        )


def _register_narrative(mcp: MCPServer) -> None:
    @mcp.tool(
        name="narrative",
        **tool_kwargs(narrative.schema),
    )
    async def tool_narrative(
        directory: str | None = None,
        domain: str | None = None,
        brief: bool = False,
    ) -> dict[str, Any]:
        """Generate project narrative from stored memories."""
        return await safe_handler(
            narrative.handler,
            {
                "directory": directory,
                "domain": domain,
                "brief": brief,
            },
            tool_name="narrative",
        )


def _register_consolidate(mcp: MCPServer) -> None:
    @mcp.tool(
        name="consolidate",
        **tool_kwargs(consolidate.schema),
    )
    async def tool_consolidate(
        decay: bool = True,
        compress: bool = True,
        cls: bool = True,
        memify: bool = True,
        deep: bool = False,
        wiki: bool = True,
        wiki_apply_stubs: bool = True,
        wiki_apply_classifier_rejects: bool = True,
        wiki_max_purges_per_axis: int = 500,
        wiki_apply_citation_seed: bool = True,
        wiki_citation_seed_limit: int | None = None,
    ) -> dict[str, Any]:
        """Run memory maintenance: decay, compression, CLS, memify."""
        return await safe_handler(
            consolidate.handler,
            {
                "decay": decay,
                "compress": compress,
                "cls": cls,
                "memify": memify,
                "deep": deep,
                "wiki": wiki,
                "wiki_apply_stubs": wiki_apply_stubs,
                "wiki_apply_classifier_rejects": wiki_apply_classifier_rejects,
                "wiki_max_purges_per_axis": wiki_max_purges_per_axis,
                "wiki_apply_citation_seed": wiki_apply_citation_seed,
                "wiki_citation_seed_limit": wiki_citation_seed_limit,
            },
            tool_name="consolidate",
        )


def _register_import_sessions(mcp: MCPServer) -> None:
    @mcp.tool(
        name="import_sessions",
        **tool_kwargs(import_sessions.schema),
    )
    async def tool_import_sessions(
        project: str | None = None,
        domain: str | None = None,
        min_importance: float = 0.4,
        max_sessions: int = 0,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Import conversation history into the memory store.

        Streams JSONL files using head and tail windows."""
        # source: ADR-0698
        return await safe_handler(
            import_sessions.handler,
            {
                "project": project or "",
                "domain": domain or "",
                "min_importance": min_importance,
                "max_sessions": max_sessions,
                "dry_run": dry_run,
            },
            tool_name="import_sessions",
        )


def _register_get_telemetry(mcp: MCPServer) -> None:
    @mcp.tool(
        name="get_telemetry",
        **tool_kwargs(get_telemetry.schema),
    )
    async def tool_get_telemetry() -> dict[str, Any]:
        """Return per-op counters + read/write ratio (Popper C6)."""
        return await safe_handler(get_telemetry.handler, {}, tool_name="get_telemetry")


def _register_get_grooming_health(mcp: MCPServer) -> None:
    @mcp.tool(
        name="get_grooming_health",
        **tool_kwargs(get_grooming_health.schema),
    )
    async def tool_get_grooming_health() -> dict[str, Any]:
        """Backlog + staleness for wiki/distillation/promotion grooming."""
        return await safe_handler(
            get_grooming_health.handler, {}, tool_name="get_grooming_health"
        )
