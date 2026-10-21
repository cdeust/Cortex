"""Promptless native role/project context, never inferred task context.

source: ADR-1085
"""

from typing import Any

from mcp_server.hooks.agent_briefing_query import _fetch_agent_context
from mcp_server.hooks.agent_briefing_sqlite import _MAX_MEMORIES, _MIN_HEAT
from mcp_server.infrastructure.hook_recall_queries import briefing_role_rows


def fetch_role_context(store: Any, agent: str, project_root: str | None) -> list:
    """Team decisions first; existing role-prior heat order fills unused slots."""
    result = _fetch_agent_context(store, agent, [], project_root)
    remaining = _MAX_MEMORIES - len(result)
    if not remaining:
        return result
    rows = store.call(briefing_role_rows, agent, project_root, _MIN_HEAT, remaining)
    result.extend(
        {
            "id": row["id"],
            "content": row["content"][:300],
            "heat": row["heat"],
            "source": "role-prior",
        }
        for row in rows
    )
    return result
