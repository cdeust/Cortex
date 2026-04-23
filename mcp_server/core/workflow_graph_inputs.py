"""Input DTO for ``WorkflowGraphBuilder.build`` — single parameter
object holding every data stream the builder consumes.

Introduced (Gap 10 audit, §4.4 coding-standard rule) to replace the
18-keyword-argument ``build`` signature that grew over time. Callers
construct a ``WorkflowBuildInputs`` with whichever streams they have
loaded (every field defaults to an empty list) and pass the single
DTO in.

Pure core logic. Stdlib + dataclasses only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowBuildInputs:
    """Every data stream ``WorkflowGraphBuilder.build`` may ingest.

    Each field is an iterable of plain dicts produced by one of the
    infrastructure loaders; the builder iterates, normalises, and
    emits ``WorkflowNode`` / ``WorkflowEdge`` instances. Unused
    streams default to empty lists so callers plug in only what they
    have.
    """

    # ── Phase 1: node-producing streams ────────────────────────────
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    skill_paths: list[dict[str, Any]] = field(default_factory=list)
    hook_defs: list[dict[str, Any]] = field(default_factory=list)
    agent_events: list[dict[str, Any]] = field(default_factory=list)
    command_events: list[dict[str, Any]] = field(default_factory=list)
    memories: list[dict[str, Any]] = field(default_factory=list)
    discussions: list[dict[str, Any]] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)

    # ── Phase 2: relational-edge streams (run after files finalise) ─
    discussion_file_events: list[dict[str, Any]] = field(default_factory=list)
    skill_usage_events: list[dict[str, Any]] = field(default_factory=list)
    command_file_events: list[dict[str, Any]] = field(default_factory=list)
    mcp_usage_events: list[dict[str, Any]] = field(default_factory=list)
    discussion_tool_events: list[dict[str, Any]] = field(default_factory=list)
    discussion_agent_events: list[dict[str, Any]] = field(default_factory=list)
    discussion_command_events: list[dict[str, Any]] = field(default_factory=list)
    memory_entity_edges: list[dict[str, Any]] = field(default_factory=list)

    # ── Phase 3: AST symbols + edges (ADR-0046) ────────────────────
    ast_symbols: list[dict[str, Any]] = field(default_factory=list)
    ast_edges: list[dict[str, Any]] = field(default_factory=list)


__all__ = ["WorkflowBuildInputs"]
