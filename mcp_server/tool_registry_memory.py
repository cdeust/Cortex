"""Tool registration: Tier 1 memory read/write tools (8 tools).

Registers remember, recall, checkpoint, consolidation, and diagnostics tools.
"""

from __future__ import annotations

import json

from fastmcp import FastMCP

from mcp_server.handlers import (
    remember,
    recall,
    memory_stats,
    checkpoint,
    consolidate,
    narrative,
    open_memory_dashboard,
    import_sessions,
)


def register(mcp: FastMCP) -> None:
    """Register Tier 1 memory read/write tools on the FastMCP instance."""
    _register_remember(mcp)
    _register_recall(mcp)
    _register_memory_stats(mcp)
    _register_checkpoint(mcp)
    _register_narrative(mcp)
    _register_consolidate(mcp)
    _register_open_memory_dashboard(mcp)
    _register_import_sessions(mcp)


def _register_remember(mcp: FastMCP) -> None:
    @mcp.tool(
        name="remember",
        description=remember.schema["description"],
    )
    async def tool_remember(
        content: str,
        tags: list[str] | None = None,
        directory: str | None = None,
        domain: str | None = None,
        source: str | None = None,
        force: bool = False,
        agent_topic: str | None = None,
    ) -> str:
        """Store a memory through the predictive coding write gate."""
        result = await remember.handler(
            {
                "content": content,
                "tags": tags or [],
                "directory": directory or "",
                "domain": domain or "",
                "source": source or "user",
                "force": force,
                "agent_topic": agent_topic or "",
            }
        )
        return json.dumps(result, indent=2, default=str)


def _register_recall(mcp: FastMCP) -> None:
    @mcp.tool(
        name="recall",
        description=recall.schema["description"],
    )
    async def tool_recall(
        query: str,
        domain: str | None = None,
        directory: str | None = None,
        max_results: int = 10,
        min_heat: float = 0.05,
        agent_topic: str | None = None,
    ) -> str:
        """Retrieve memories using multi-signal fusion."""
        result = await recall.handler(
            {
                "query": query,
                "domain": domain,
                "directory": directory,
                "max_results": max_results,
                "min_heat": min_heat,
                "agent_topic": agent_topic,
            }
        )
        return json.dumps(result, indent=2, default=str)


def _register_memory_stats(mcp: FastMCP) -> None:
    @mcp.tool(
        name="memory_stats",
        description=memory_stats.schema["description"],
    )
    async def tool_memory_stats() -> str:
        """Memory system diagnostics."""
        result = await memory_stats.handler()
        return json.dumps(result, indent=2, default=str)


def _register_checkpoint(mcp: FastMCP) -> None:
    @mcp.tool(
        name="checkpoint",
        description=checkpoint.schema["description"],
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
    ) -> str:
        """Save or restore working state for hippocampal replay."""
        result = await checkpoint.handler(
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
            }
        )
        return json.dumps(result, indent=2, default=str)


def _register_narrative(mcp: FastMCP) -> None:
    @mcp.tool(
        name="narrative",
        description=narrative.schema["description"],
    )
    async def tool_narrative(
        directory: str | None = None,
        domain: str | None = None,
        brief: bool = False,
    ) -> str:
        """Generate project narrative from stored memories."""
        result = await narrative.handler(
            {
                "directory": directory,
                "domain": domain,
                "brief": brief,
            }
        )
        return json.dumps(result, indent=2, default=str)


def _register_consolidate(mcp: FastMCP) -> None:
    @mcp.tool(
        name="consolidate",
        description=consolidate.schema["description"],
    )
    async def tool_consolidate(
        decay: bool = True,
        compress: bool = True,
        cls: bool = True,
        memify: bool = True,
        deep: bool = False,
    ) -> str:
        """Run memory maintenance: decay, compression, CLS, memify."""
        result = await consolidate.handler(
            {
                "decay": decay,
                "compress": compress,
                "cls": cls,
                "memify": memify,
                "deep": deep,
            }
        )
        return json.dumps(result, indent=2, default=str)


def _register_open_memory_dashboard(mcp: FastMCP) -> None:
    @mcp.tool(
        name="open_memory_dashboard",
        description=open_memory_dashboard.schema["description"],
    )
    async def tool_open_memory_dashboard() -> str:
        """Launch the real-time memory dashboard in the browser."""
        result = await open_memory_dashboard.handler()
        return json.dumps(result, indent=2, default=str)


def _register_import_sessions(mcp: FastMCP) -> None:
    @mcp.tool(
        name="import_sessions",
        description=import_sessions.schema["description"],
    )
    async def tool_import_sessions(
        project: str | None = None,
        domain: str | None = None,
        min_importance: float = 0.4,
        max_sessions: int = 0,
        dry_run: bool = False,
        full_read: bool = False,
    ) -> str:
        """Import conversation history into the memory store."""
        result = await import_sessions.handler(
            {
                "project": project or "",
                "domain": domain or "",
                "min_importance": min_importance,
                "max_sessions": max_sessions,
                "dry_run": dry_run,
                "full_read": full_read,
            }
        )
        return json.dumps(result, indent=2, default=str)
