"""Tool registration: Tier 3 advanced tools (6 tools).

Registers automation, rules, narrative, and coverage tools.
"""

from __future__ import annotations

from fastmcp import FastMCP

from mcp_server.handlers import (
    add_rule,
    assess_coverage,
    create_trigger,
    get_project_story,
    get_rules,
    sync_instructions,
)
from mcp_server.tool_error_handler import safe_handler


def register(mcp: FastMCP) -> None:
    """Register Tier 3 advanced tools."""
    _register_sync_instructions(mcp)
    _register_create_trigger(mcp)
    _register_add_rule(mcp)
    _register_get_rules(mcp)
    _register_get_project_story(mcp)
    _register_assess_coverage(mcp)


def _register_sync_instructions(mcp: FastMCP) -> None:
    @mcp.tool(
        name="sync_instructions",
        description=sync_instructions.schema["description"],
    )
    async def tool_sync_instructions(
        directory: str | None = None,
        max_insights: int = 10,
        min_heat: float = 0.3,
        dry_run: bool = False,
    ) -> str:
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
        description=create_trigger.schema["description"],
    )
    async def tool_create_trigger(
        content: str,
        trigger_condition: str,
        trigger_type: str = "keyword",
        target_directory: str | None = None,
    ) -> str:
        """Create a prospective memory trigger."""
        return await safe_handler(
            create_trigger.handler,
            {
                "content": content,
                "trigger_condition": trigger_condition,
                "trigger_type": trigger_type,
                "target_directory": target_directory,
            },
            tool_name="create_trigger",
        )


def _register_add_rule(mcp: FastMCP) -> None:
    @mcp.tool(
        name="add_rule",
        description=add_rule.schema["description"],
    )
    async def tool_add_rule(
        condition: str,
        action: str,
        rule_type: str = "soft",
        scope: str = "global",
        scope_value: str | None = None,
        priority: int = 0,
    ) -> str:
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
            },
            tool_name="add_rule",
        )


def _register_get_rules(mcp: FastMCP) -> None:
    @mcp.tool(
        name="get_rules",
        description=get_rules.schema["description"],
    )
    async def tool_get_rules(
        scope: str | None = None,
        rule_type: str | None = None,
        include_inactive: bool = False,
    ) -> str:
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
        description=get_project_story.schema["description"],
    )
    async def tool_get_project_story(
        directory: str | None = None,
        domain: str | None = None,
        period: str = "week",
        max_chapters: int = 5,
    ) -> str:
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
        description=assess_coverage.schema["description"],
    )
    async def tool_assess_coverage(
        directory: str | None = None,
        domain: str | None = None,
        stale_days: int = 14,
    ) -> str:
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
