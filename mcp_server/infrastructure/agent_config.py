"""Agent registry — defines the team of functional agents and their Cortex memory usage.

Each agent is a Claude Code subagent defined in .claude/agents/*.md. They use
Cortex's MCP tools (recall, remember, etc.) as their knowledge base. The
registry maps each agent to the tools it uses, enabling the graph builder to
show agent nodes and tool ownership in the visualization.

Key principle: recall before working, remember the why after — never remember
what's already in the code or git history.

Pure configuration — no I/O.
"""

from __future__ import annotations

AGENT_REGISTRY: list[dict] = [
    # ── orchestrator ───────────────────────────────────────────────
    {
        "name": "Orchestrator",
        "project": "cortex",
        "agent_file": "orchestrator.md",
        "topic": "orchestrator",
        "description": "Decomposes tasks, spawns specialized agents in parallel worktrees, coordinates and merges",
        "recalls": [
            "recall",
            "recall_hierarchical",
            "get_causal_chain",
            "memory_stats",
            "detect_gaps",
            "get_project_story",
        ],
        "remembers": ["remember", "anchor", "checkpoint", "consolidate", "narrative"],
        "tools": [
            "recall",
            "recall_hierarchical",
            "get_causal_chain",
            "memory_stats",
            "detect_gaps",
            "get_project_story",
            "remember",
            "anchor",
            "checkpoint",
            "consolidate",
            "narrative",
        ],
    },
    # ── engineer ───────────────────────────────────────────────────
    {
        "name": "Engineer",
        "project": "cortex",
        "agent_file": "engineer.md",
        "topic": "engineer",
        "description": "Clean Architecture, SOLID, root-cause problem solving — adapts to any language",
        "recalls": ["recall", "get_causal_chain", "get_rules", "recall_hierarchical"],
        "remembers": ["remember"],
        "tools": [
            "recall",
            "get_causal_chain",
            "get_rules",
            "recall_hierarchical",
            "remember",
        ],
    },
    # ── tester ─────────────────────────────────────────────────────
    {
        "name": "Tester",
        "project": "cortex",
        "agent_file": "tester.md",
        "topic": "tester",
        "description": "Test strategy, coverage analysis, fragile module detection",
        "recalls": ["recall", "detect_gaps", "get_rules"],
        "remembers": ["remember"],
        "tools": ["recall", "detect_gaps", "get_rules", "remember"],
    },
    # ── reviewer ───────────────────────────────────────────────────
    {
        "name": "Reviewer",
        "project": "cortex",
        "agent_file": "reviewer.md",
        "topic": "reviewer",
        "description": "Code review, ADR enforcement, accepted trade-off tracking",
        "recalls": ["recall", "get_rules", "recall_hierarchical"],
        "remembers": ["remember", "add_rule"],
        "tools": ["recall", "get_rules", "recall_hierarchical", "remember", "add_rule"],
    },
    # ── ux ─────────────────────────────────────────────────────────
    {
        "name": "UX",
        "project": "cortex",
        "agent_file": "ux.md",
        "topic": "ux",
        "description": "UX decisions, accessibility, design rationale, user constraints",
        "recalls": ["recall", "recall_hierarchical"],
        "remembers": ["remember"],
        "tools": ["recall", "recall_hierarchical", "remember"],
    },
    # ── frontend ───────────────────────────────────────────────────
    {
        "name": "Frontend",
        "project": "cortex",
        "agent_file": "frontend.md",
        "topic": "frontend",
        "description": "Component architecture, UX integration, frontend patterns",
        "recalls": ["recall", "get_rules", "recall_hierarchical"],
        "remembers": ["remember"],
        "tools": ["recall", "get_rules", "recall_hierarchical", "remember"],
    },
    # ── security ───────────────────────────────────────────────────
    {
        "name": "Security",
        "project": "cortex",
        "agent_file": "security.md",
        "topic": "security",
        "description": "Threat models, accepted risks, dependency audits, data flow analysis",
        "recalls": ["recall", "get_causal_chain", "detect_gaps"],
        "remembers": ["remember", "add_rule"],
        "tools": ["recall", "get_causal_chain", "detect_gaps", "remember", "add_rule"],
    },
    # ── researcher ─────────────────────────────────────────────────
    {
        "name": "Researcher",
        "project": "cortex",
        "agent_file": "researcher.md",
        "topic": "researcher",
        "description": "Paper reviews, benchmark analysis, competitive intelligence, negative results",
        "recalls": ["recall", "recall_hierarchical", "detect_gaps", "assess_coverage"],
        "remembers": ["remember"],
        "tools": [
            "recall",
            "recall_hierarchical",
            "detect_gaps",
            "assess_coverage",
            "remember",
        ],
    },
    # ── dba ────────────────────────────────────────────────────────
    {
        "name": "DBA",
        "project": "cortex",
        "agent_file": "dba.md",
        "topic": "dba",
        "description": "Schema decisions, query optimization, migration lessons",
        "recalls": ["recall", "get_causal_chain", "get_rules"],
        "remembers": ["remember"],
        "tools": ["recall", "get_causal_chain", "get_rules", "remember"],
    },
    # ── devops ─────────────────────────────────────────────────────
    {
        "name": "DevOps",
        "project": "cortex",
        "agent_file": "devops.md",
        "topic": "devops",
        "description": "Infrastructure decisions, incident postmortems, env parity",
        "recalls": ["recall", "get_causal_chain", "recall_hierarchical"],
        "remembers": ["remember"],
        "tools": ["recall", "get_causal_chain", "recall_hierarchical", "remember"],
    },
    # ── architect ──────────────────────────────────────────────────
    {
        "name": "Architect",
        "project": "cortex",
        "agent_file": "architect.md",
        "topic": "architect",
        "description": "ADRs, decomposition plans, refactoring strategy, project story",
        "recalls": [
            "recall",
            "recall_hierarchical",
            "get_project_story",
            "get_causal_chain",
        ],
        "remembers": ["remember", "anchor"],
        "tools": [
            "recall",
            "recall_hierarchical",
            "get_project_story",
            "get_causal_chain",
            "remember",
            "anchor",
        ],
    },
    # ── pipeline (ai-architect integration) ────────────────────────
    {
        "name": "Pipeline",
        "project": "ai architect",
        "agent_file": None,
        "topic": "pipeline",
        "description": "End-to-end PRD and architecture pipeline",
        "recalls": [],
        "remembers": [],
        "tools": ["run_pipeline"],
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


def get_agent_topic(agent_name: str) -> str:
    """Return the memory topic for an agent (case-insensitive)."""
    low = agent_name.lower()
    for a in AGENT_REGISTRY:
        if a["name"].lower() == low:
            return a.get("topic", low)
    return low
