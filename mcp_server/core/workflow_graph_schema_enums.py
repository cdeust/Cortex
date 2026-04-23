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
    # ENTITY — projects a knowledge-graph entity (entities table row)
    # into the workflow graph. Produced by
    # ``workflow_graph_source_pg.load_entities`` and ingested by
    # ``WorkflowGraphBuilder._ingest_entity``. Linked to memories via
    # the ``about_entity`` edge. Colour comes from the legacy palette
    # (ENTITY_COLORS) matched on ``entityType``.
    ENTITY = "entity"
    MCP = "mcp"
    # SYMBOL — function / class / module / import extracted from the
    # AST by the ``automatised-pipeline`` sibling plugin (ADR-0046).
    # ``symbol_type`` on the node body carries the sub-kind.
    SYMBOL = "symbol"


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
    # ABOUT_ENTITY — MEMORY → ENTITY link. Produced by
    # ``WorkflowGraphBuilder._ingest_memory_entity_edge`` which reads
    # the ``memory_entities`` join table. Styled in
    # ``ui/unified/workflow_graph.css`` (``.wfg-link--about_entity``).
    ABOUT_ENTITY = "about_entity"
    DISCUSSION_TOUCHED_FILE = "discussion_touched_file"
    DISCUSSION_USED_TOOL = "discussion_used_tool"
    DISCUSSION_SPAWNED_AGENT = "discussion_spawned_agent"
    DISCUSSION_RAN_COMMAND = "discussion_ran_command"
    COMMAND_TOUCHED_FILE = "command_touched_file"
    INVOKED_MCP = "invoked_mcp"
    # AST edges produced by the ``automatised-pipeline`` bridge
    # (ADR-0046). All source-symbols must resolve to a SYMBOL node;
    # targets resolve to a SYMBOL (CALLS, MEMBER_OF) or a FILE
    # (DEFINED_IN) or a SYMBOL import (IMPORTS).
    DEFINED_IN = "defined_in"  # symbol → file
    CALLS = "calls"  # caller symbol → callee symbol
    IMPORTS = "imports"  # file → imported symbol or file
    MEMBER_OF = "member_of"  # function → class / class → module


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
