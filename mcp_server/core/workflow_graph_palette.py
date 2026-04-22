"""Color palette for the workflow graph — tuned for maximum kind separation.

Each semantic family sits in a distinct hue band so glance-to-legend
identifies which node to click:

* YELLOW/GOLD → Cortex identity + shell (domain, command)
* ORANGE     → user-invoked slash commands (skill)
* PINK/RED   → human-actor interactions (agent, task, discussion)
* PURPLE     → integrations (hook, MCP)
* GREEN      → authorship (edit/write + memory lifecycle)
* CYAN       → information intake (read)
* FUCHSIA    → search (grep/glob)

Pure data. Imports the enum types from ``workflow_graph_schema`` so the
palette can stay keyed by ``ToolKind`` / ``PrimaryToolCluster`` without
a circular dependency (this module is only imported by the schema and
builder — never the other way round).
"""

from __future__ import annotations

from mcp_server.core.workflow_graph_schema_enums import (
    PrimaryToolCluster,
    ToolKind,
)

DOMAIN_COLOR = "#FCD34D"       # gold — hub
SKILL_COLOR = "#FB923C"        # orange — slash commands / skills
COMMAND_COLOR = "#FACC15"      # yellow — distinct from Bash-tool orange
HOOK_COLOR = "#A855F7"         # purple — settings hooks
AGENT_COLOR = "#EC4899"        # bright pink — subagents
DISCUSSION_COLOR = "#EF4444"   # red — session anchors
ENTITY_COLOR = "#50B0C8"       # teal — extracted entities
MCP_COLOR = "#6366F1"          # indigo — MCP servers (distinct from hook)

TOOL_HUB_COLORS: dict[ToolKind, str] = {
    ToolKind.EDIT: "#10B981",   # emerald
    ToolKind.WRITE: "#059669",  # dark emerald — paired with Edit
    ToolKind.READ: "#06B6D4",   # cyan — far from every green
    ToolKind.GREP: "#D946EF",   # fuchsia
    ToolKind.GLOB: "#C026D3",   # deeper fuchsia — paired with Grep
    ToolKind.BASH: "#F97316",   # orange — shell band
    ToolKind.TASK: "#EC4899",   # pink — paired with Agent
}

PRIMARY_TOOL_COLORS: dict[PrimaryToolCluster, str] = {
    PrimaryToolCluster.EDIT_WRITE: "#10B981",   # emerald — files you author
    PrimaryToolCluster.READ: "#06B6D4",         # cyan — files you only read
    PrimaryToolCluster.GREP_GLOB: "#D946EF",    # fuchsia — files you only searched
    PrimaryToolCluster.BASH: "#F97316",         # orange — files touched only by shell
}

MEMORY_STAGE_COLORS: dict[str, str] = {
    "labile": "#86EFAC",
    "early_ltp": "#4ADE80",
    "late_ltp": "#16A34A",
    "consolidated": "#166534",
    "episodic": "#58D888",
    "semantic": "#C070D0",
}


def primary_tool_color(cluster: PrimaryToolCluster) -> str:
    """Return the file color dictated by the primary-tool meta-rule."""
    return PRIMARY_TOOL_COLORS[cluster]


def classify_primary_tool(
    tool_counts: dict[ToolKind, int],
) -> PrimaryToolCluster:
    """Apply the primary-tool meta-rule: Edit/Write > Read > Grep/Glob > Bash."""
    if tool_counts.get(ToolKind.EDIT, 0) or tool_counts.get(ToolKind.WRITE, 0):
        return PrimaryToolCluster.EDIT_WRITE
    if tool_counts.get(ToolKind.READ, 0):
        return PrimaryToolCluster.READ
    if tool_counts.get(ToolKind.GREP, 0) or tool_counts.get(ToolKind.GLOB, 0):
        return PrimaryToolCluster.GREP_GLOB
    return PrimaryToolCluster.BASH
