"""Enum vocabulary for the workflow graph — factored out so the palette
module (``workflow_graph_palette``) can key dicts by these types
without pulling the pydantic model definitions in.

Pure stdlib. No imports from the rest of the workflow-graph stack.
"""

from __future__ import annotations

from enum import Enum


class NodeKind(str, Enum):
    DOMAIN = "domain"
    SKILL = "skill"
    COMMAND = "command"
    HOOK = "hook"
    AGENT = "agent"
    TOOL_HUB = "tool_hub"
    FILE = "file"
    MEMORY = "memory"
    DISCUSSION = "discussion"
    # ENTITY is reserved for the future knowledge-graph entity projection.
    # No ingest path currently produces entity nodes; the JS renderer
    # palette includes it so the schema stays forward-compatible.
    ENTITY = "entity"
    MCP = "mcp"


class EdgeKind(str, Enum):
    IN_DOMAIN = "in_domain"
    TOOL_USED_FILE = "tool_used_file"
    # Bash hub → command node containment edge. Distinct from
    # TOOL_USED_FILE so that the panel's "Files touched" counter does
    # not mistakenly include commands.
    COMMAND_IN_HUB = "command_in_hub"
    INVOKED_SKILL = "invoked_skill"
    TRIGGERED_HOOK = "triggered_hook"
    SPAWNED_AGENT = "spawned_agent"
    # ABOUT_ENTITY — paired with NodeKind.ENTITY. Reserved for the
    # future knowledge-graph entity projection; no current producer.
    ABOUT_ENTITY = "about_entity"
    DISCUSSION_TOUCHED_FILE = "discussion_touched_file"
    DISCUSSION_USED_TOOL = "discussion_used_tool"
    DISCUSSION_SPAWNED_AGENT = "discussion_spawned_agent"
    DISCUSSION_RAN_COMMAND = "discussion_ran_command"
    COMMAND_TOUCHED_FILE = "command_touched_file"
    INVOKED_MCP = "invoked_mcp"


class ToolKind(str, Enum):
    EDIT = "Edit"
    READ = "Read"
    GREP = "Grep"
    BASH = "Bash"
    GLOB = "Glob"
    WRITE = "Write"
    TASK = "Task"


class PrimaryToolCluster(str, Enum):
    EDIT_WRITE = "edit_write"
    READ = "read"
    GREP_GLOB = "grep_glob"
    BASH = "bash"
