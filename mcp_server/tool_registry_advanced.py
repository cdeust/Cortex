"""Tool registration: Tier 3 advanced tools (7 tools).

Registers automation, rules, narrative, and coverage tools.
"""

from __future__ import annotations

from fastmcp import FastMCP

from mcp_server.handlers import (
    add_rule,
    assess_coverage,
    create_trigger,
    curate_distill,
    curate_wiki,
    get_project_story,
    get_rules,
    lesson_promotion,
    sync_instructions,
)
from mcp_server.tool_error_handler import safe_handler
from mcp_server.handlers._tool_meta import tool_kwargs


# Tool name → handler schema; __main__ hands the merged map to
# _tool_meta.apply_param_docs after registration.
SCHEMAS: dict[str, dict] = {
    "add_rule": add_rule.schema,
    "assess_coverage": assess_coverage.schema,
    "create_trigger": create_trigger.schema,
    "curate_distill": curate_distill.schema,
    "curate_wiki": curate_wiki.schema,
    "get_project_story": get_project_story.schema,
    "get_rules": get_rules.schema,
    "lesson_promotion": lesson_promotion.schema,
    "sync_instructions": sync_instructions.schema,
}


def register(mcp: FastMCP) -> None:
    """Register Tier 3 advanced tools."""
    _register_sync_instructions(mcp)
    _register_create_trigger(mcp)
    _register_add_rule(mcp)
    _register_get_rules(mcp)
    _register_get_project_story(mcp)
    _register_assess_coverage(mcp)
    _register_curate_wiki(mcp)
    _register_lesson_promotion(mcp)
    _register_curate_distill(mcp)


def _register_curate_wiki(mcp: FastMCP) -> None:
    @mcp.tool(
        name="curate_wiki",
        **tool_kwargs(curate_wiki.schema),
    )
    async def tool_curate_wiki(
        domain: str | None = None,
        limit: int = 3,
        min_memories: int = 4,
        min_avg_heat: float = 0.3,
        recent_only: bool = True,
        memory_pool_size: int = 500,
    ) -> dict:
        """Return structured authoring jobs for the in-session LLM to author."""
        return await safe_handler(
            curate_wiki.handler,
            {
                "domain": domain,
                "limit": limit,
                "min_memories": min_memories,
                "min_avg_heat": min_avg_heat,
                "recent_only": recent_only,
                "memory_pool_size": memory_pool_size,
            },
            tool_name="curate_wiki",
        )


def _register_lesson_promotion(mcp: FastMCP) -> None:
    @mcp.tool(
        name="lesson_promotion",
        **tool_kwargs(lesson_promotion.schema),
    )
    async def tool_lesson_promotion(limit: int = 10) -> dict:
        """Propose promotion jobs for validated lessons — never promotes itself."""
        return await safe_handler(
            lesson_promotion.handler,
            {"limit": limit},
            tool_name="lesson_promotion",
        )


def _register_curate_distill(mcp: FastMCP) -> None:
    @mcp.tool(
        name="curate_distill",
        **tool_kwargs(curate_distill.schema),
    )
    async def tool_curate_distill(
        domain: str | None = None,
        limit: int = 5,
        window_hours: float = 168.0,
        include_error_success: bool = True,
        include_co_access: bool = True,
        include_entity_family: bool = True,
        min_memories: int = 4,
        min_avg_heat: float = 0.3,
        memory_pool_size: int = 500,
    ) -> dict:
        """Return distillation dossiers for the in-session LLM to author
        lessons from."""
        return await safe_handler(
            curate_distill.handler,
            {
                "domain": domain,
                "limit": limit,
                "window_hours": window_hours,
                "include_error_success": include_error_success,
                "include_co_access": include_co_access,
                "include_entity_family": include_entity_family,
                "min_memories": min_memories,
                "min_avg_heat": min_avg_heat,
                "memory_pool_size": memory_pool_size,
            },
            tool_name="curate_distill",
        )


def _register_sync_instructions(mcp: FastMCP) -> None:
    @mcp.tool(
        name="sync_instructions",
        **tool_kwargs(sync_instructions.schema),
    )
    async def tool_sync_instructions(
        directory: str | None = None,
        max_insights: int = 10,
        min_heat: float = 0.3,
        dry_run: bool = False,
    ) -> dict:
        """Push top memory insights into CLAUDE.md."""
        return await safe_handler(
            sync_instructions.handler,
            {
                "directory": directory or "",
                "max_insights": max_insights,
                "min_heat": min_heat,
                "dry_run": dry_run,
            },
            tool_name="sync_instructions",
        )


def _register_create_trigger(mcp: FastMCP) -> None:
    @mcp.tool(
        name="create_trigger",
        **tool_kwargs(create_trigger.schema),
    )
    async def tool_create_trigger(
        content: str,
        trigger_condition: str,
        trigger_type: str = "keyword",
        target_directory: str | None = None,
        source_memory_id: int | None = None,
    ) -> dict:
        """Create a prospective memory trigger."""
        return await safe_handler(
            create_trigger.handler,
            {
                "content": content,
                "trigger_condition": trigger_condition,
                "trigger_type": trigger_type,
                "target_directory": target_directory,
                "source_memory_id": source_memory_id,
            },
            tool_name="create_trigger",
        )


def _register_add_rule(mcp: FastMCP) -> None:
    @mcp.tool(
        name="add_rule",
        **tool_kwargs(add_rule.schema),
    )
    async def tool_add_rule(
        condition: str,
        action: str,
        rule_type: str = "soft",
        scope: str = "global",
        scope_value: str | None = None,
        priority: int = 0,
        source_memory_id: int | None = None,
    ) -> dict:
        """Add a neuro-symbolic rule to the memory store."""
        return await safe_handler(
            add_rule.handler,
            {
                "condition": condition,
                "action": action,
                "rule_type": rule_type,
                "scope": scope,
                "scope_value": scope_value,
                "priority": priority,
                "source_memory_id": source_memory_id,
            },
            tool_name="add_rule",
        )


def _register_get_rules(mcp: FastMCP) -> None:
    @mcp.tool(
        name="get_rules",
        **tool_kwargs(get_rules.schema),
    )
    async def tool_get_rules(
        scope: str | None = None,
        rule_type: str | None = None,
        include_inactive: bool = False,
    ) -> dict:
        """List active neuro-symbolic rules."""
        return await safe_handler(
            get_rules.handler,
            {
                "scope": scope,
                "rule_type": rule_type,
                "include_inactive": include_inactive,
            },
            tool_name="get_rules",
        )


def _register_get_project_story(mcp: FastMCP) -> None:
    @mcp.tool(
        name="get_project_story",
        **tool_kwargs(get_project_story.schema),
    )
    async def tool_get_project_story(
        directory: str | None = None,
        domain: str | None = None,
        period: str = "week",
        max_chapters: int = 5,
    ) -> dict:
        """Generate a period-based autobiographical narrative."""
        return await safe_handler(
            get_project_story.handler,
            {
                "directory": directory,
                "domain": domain,
                "period": period,
                "max_chapters": max_chapters,
            },
            tool_name="get_project_story",
        )


def _register_assess_coverage(mcp: FastMCP) -> None:
    @mcp.tool(
        name="assess_coverage",
        **tool_kwargs(assess_coverage.schema),
    )
    async def tool_assess_coverage(
        directory: str | None = None,
        domain: str | None = None,
        stale_days: int = 14,
    ) -> dict:
        """Evaluate knowledge coverage completeness."""
        return await safe_handler(
            assess_coverage.handler,
            {
                "directory": directory or "",
                "domain": domain or "",
                "stale_days": stale_days,
            },
            tool_name="assess_coverage",
        )
