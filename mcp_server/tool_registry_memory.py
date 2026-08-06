"""Tool registration: Tier 1 memory read/write tools (9 tools).

Registers remember, recall, checkpoint, consolidation, and diagnostics tools.
"""

from __future__ import annotations

from fastmcp import FastMCP

from mcp_server.handlers import (
    checkpoint,
    consolidate,
    get_grooming_health,
    get_telemetry,
    import_sessions,
    memory_stats,
    narrative,
    recall,
    remember,
    unified_search,
)
from mcp_server.infrastructure.memory_config import root_agent_topic
from mcp_server.tool_error_handler import safe_handler
from mcp_server.handlers._tool_meta import tool_kwargs


# Tool name → handler schema; __main__ hands the merged map to
# _tool_meta.apply_param_docs after registration.
SCHEMAS: dict[str, dict] = {
    "remember": remember.schema,
    "recall": recall.schema,
    "memory_stats": memory_stats.schema,
    "checkpoint": checkpoint.schema,
    "narrative": narrative.schema,
    "consolidate": consolidate.schema,
    "import_sessions": import_sessions.schema,
    "unified_search": unified_search.schema,
    "get_telemetry": get_telemetry.schema,
    "get_grooming_health": get_grooming_health.schema,
}


def register(mcp: FastMCP) -> None:
    """Register Tier 1 memory read/write tools on the FastMCP instance."""
    _register_remember(mcp)
    _register_recall(mcp)
    _register_memory_stats(mcp)
    _register_checkpoint(mcp)
    _register_narrative(mcp)
    _register_consolidate(mcp)
    _register_import_sessions(mcp)
    _register_unified_search(mcp)
    _register_get_telemetry(mcp)
    _register_get_grooming_health(mcp)


def _register_remember(mcp: FastMCP) -> None:
    # Connection-rooted scoping: when CORTEX_ROOT_AGENT_TOPIC is set the
    # agent_topic parameter is omitted from the registered signature
    # (FastMCP derives the input schema from the signature), so the model
    # never sees it. The handler forces the root topic server-side.
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
        ) -> dict:
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
    ) -> dict:
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
            },
            tool_name="remember",
        )


def _register_recall(mcp: FastMCP) -> None:
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
        ) -> dict:
            """Retrieve memories using multi-signal fusion."""
            return await safe_handler(
                recall.handler,
                {
                    "query": query,
                    "domain": domain,
                    "directory": directory,
                    "max_results": max_results,
                    "min_heat": min_heat,
                    "include_related": include_related,
                    "format": format,
                },
                tool_name="recall",
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
    ) -> dict:
        """Retrieve memories using multi-signal fusion."""
        return await safe_handler(
            recall.handler,
            {
                "query": query,
                "domain": domain,
                "directory": directory,
                "max_results": max_results,
                "min_heat": min_heat,
                "agent_topic": agent_topic,
                "include_related": include_related,
                "format": format,
            },
            tool_name="recall",
        )


def _register_memory_stats(mcp: FastMCP) -> None:
    @mcp.tool(
        name="memory_stats",
        **tool_kwargs(memory_stats.schema),
    )
    async def tool_memory_stats() -> dict:
        """Memory system diagnostics."""
        return await safe_handler(memory_stats.handler, {}, tool_name="memory_stats")


def _register_checkpoint(mcp: FastMCP) -> None:
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
    ) -> dict:
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


def _register_narrative(mcp: FastMCP) -> None:
    @mcp.tool(
        name="narrative",
        **tool_kwargs(narrative.schema),
    )
    async def tool_narrative(
        directory: str | None = None,
        domain: str | None = None,
        brief: bool = False,
    ) -> dict:
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


def _register_consolidate(mcp: FastMCP) -> None:
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
    ) -> dict:
        """Run memory maintenance: decay, compression, CLS, memify."""
        return await safe_handler(
            consolidate.handler,
            {
                "decay": decay,
                "compress": compress,
                "cls": cls,
                "memify": memify,
                "deep": deep,
            },
            tool_name="consolidate",
        )


def _register_import_sessions(mcp: FastMCP) -> None:
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
    ) -> dict:
        """Import conversation history into the memory store.

        Always streams JSONL files via head+tail (ADR-0045 R2). The legacy
        ``full_read`` parameter was removed in v3.13.0 Phase 1 because it
        loaded entire JSONLs into Python memory (OOM path).
        """
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


def _register_get_telemetry(mcp: FastMCP) -> None:
    @mcp.tool(
        name="get_telemetry",
        **tool_kwargs(get_telemetry.schema),
    )
    async def tool_get_telemetry() -> dict:
        """Return per-op counters + read/write ratio (Popper C6)."""
        return await safe_handler(get_telemetry.handler, {}, tool_name="get_telemetry")


def _register_get_grooming_health(mcp: FastMCP) -> None:
    @mcp.tool(
        name="get_grooming_health",
        **tool_kwargs(get_grooming_health.schema),
    )
    async def tool_get_grooming_health() -> dict:
        """Backlog + staleness for wiki/distillation/promotion grooming."""
        return await safe_handler(
            get_grooming_health.handler, {}, tool_name="get_grooming_health"
        )


def _register_unified_search(mcp: FastMCP) -> None:
    @mcp.tool(
        name="unified_search",
        **tool_kwargs(unified_search.schema),
    )
    async def tool_unified_search(
        query: str,
        domain: str | None = None,
        max_results: int = 10,
        k: int = 60,
    ) -> dict:
        """RRF-fuse Cortex memory recall with AP code search (ADR-0046 P3)."""
        return await safe_handler(
            unified_search.handler,
            {
                "query": query,
                "domain": domain,
                "max_results": max_results,
                "k": k,
            },
            tool_name="unified_search",
        )
