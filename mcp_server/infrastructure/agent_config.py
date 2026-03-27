"""Agent registry — defines functional agents and their tool ownership.

Each agent belongs to a project and owns a set of MCP tools. Used by the
graph builder to create agent nodes in the hierarchical visualization.

Pure configuration — no I/O.
"""

from __future__ import annotations

AGENT_REGISTRY: list[dict] = [
    # ── cortex agents ──────────────────────────────────────────────
    {
        "name": "Memory Agent",
        "project": "cortex",
        "description": "Persistent memory with thermodynamic heat/decay",
        "tools": [
            "remember",
            "recall",
            "recall_hierarchical",
            "consolidate",
            "forget",
            "checkpoint",
            "anchor",
            "rate_memory",
            "validate_memory",
            "memory_stats",
            "backfill_memories",
            "import_sessions",
        ],
    },
    {
        "name": "Navigation Agent",
        "project": "cortex",
        "description": "Memory exploration and knowledge traversal",
        "tools": [
            "drill_down",
            "navigate_memory",
            "get_causal_chain",
            "detect_gaps",
            "narrative",
            "get_project_story",
            "assess_coverage",
        ],
    },
    {
        "name": "Profiling Agent",
        "project": "cortex",
        "description": "Cognitive profiling and methodology extraction",
        "tools": [
            "query_methodology",
            "detect_domain",
            "rebuild_profiles",
            "list_domains",
            "record_session_end",
            "explore_features",
            "get_methodology_graph",
        ],
    },
    {
        "name": "Automation Agent",
        "project": "cortex",
        "description": "Rules, triggers, and instruction sync",
        "tools": [
            "sync_instructions",
            "create_trigger",
            "add_rule",
            "get_rules",
            "seed_project",
        ],
    },
    {
        "name": "Visualization Agent",
        "project": "cortex",
        "description": "Interactive graph and dashboard visualization",
        "tools": [
            "open_visualization",
            "open_memory_dashboard",
        ],
    },
    # ── ai-architect agents ────────────────────────────────────────
    {
        "name": "Pipeline Agent",
        "project": "ai architect",
        "description": "End-to-end PRD and architecture pipeline",
        "tools": [
            "run_pipeline",
        ],
    },
]

# ── Lookup functions ─────────────────────────────────────────────────


def get_agents_for_project(project_key: str) -> list[dict]:
    """Return agents belonging to a project (case-insensitive match)."""
    low = project_key.lower()
    return [a for a in AGENT_REGISTRY if a["project"].lower() == low]


def get_all_agents() -> list[dict]:
    """Return all registered agents."""
    return list(AGENT_REGISTRY)


def get_all_tool_names() -> set[str]:
    """Return the set of all tool names owned by any agent."""
    tools: set[str] = set()
    for agent in AGENT_REGISTRY:
        tools.update(agent["tools"])
    return tools
