"""Composition root for the workflow graph.

Wires ``WorkflowGraphSource`` (infrastructure) to ``WorkflowGraphBuilder``
(core) and validates via ``validate_graph``. Returns a JSON-serializable
payload shaped for the D3 renderer in ui/unified/js/workflow_graph.js.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.workflow_graph_builder import WorkflowGraphBuilder
from mcp_server.core.workflow_graph_schema import (
    GraphValidationError,
    validate_graph,
)
from mcp_server.infrastructure.workflow_graph_source import WorkflowGraphSource
from mcp_server.infrastructure.workflow_graph_source_ast import (
    WorkflowGraphASTSource,
)


_GLOBAL_DOMAIN_TOKEN = "__global__"


def _plain_domain(domain_id: str | None) -> str:
    """Strip the ``domain:`` prefix so JS views can filter by plain label."""
    if not domain_id:
        return ""
    if domain_id.startswith("domain:"):
        return domain_id.split(":", 1)[1]
    return domain_id


# Snake_case → camelCase aliases for UI compatibility. The card
# renderers (knowledge.js, timeline.js) predate the v1 schema and read
# camelCase field names; the schema itself stays snake_case.
_CAMEL_ALIASES = {
    "consolidation_stage": "consolidationStage",
    "heat_base": "heatBase",
    "hours_in_stage": "hoursInStage",
    "stage_entered_at": "stageEnteredAt",
    "access_count": "accessCount",
    "useful_count": "usefulCount",
    "replay_count": "replayCount",
    "reconsolidation_count": "reconsolidationCount",
    "surprise_score": "surpriseScore",
    "emotional_valence": "emotionalValence",
    "dominant_emotion": "dominantEmotion",
    "hippocampal_dependency": "hippocampalDependency",
    "schema_match_score": "schemaMatchScore",
    "schema_id": "schemaId",
    "separation_index": "separationIndex",
    "interference_score": "interferenceScore",
    "encoding_strength": "encodingStrength",
    "compression_level": "compressionLevel",
    "store_type": "storeType",
    "is_protected": "isProtected",
    "is_stale": "isStale",
    "is_benchmark": "isBenchmark",
    "is_global": "isGlobal",
    "no_decay": "noDecay",
    "last_accessed": "lastAccessed",
    "created_at": "createdAt",
    "subagent_type": "subagentType",
    "session_id": "sessionId",
}


def _node_to_dict(n) -> dict[str, Any]:
    d = n.model_dump(exclude_none=True)
    # D3 convention
    d["type"] = d["kind"]
    # Legacy UI compatibility — knowledge.js / timeline.js expect a plain
    # ``domain`` label and ``isGlobal`` flag on every node. The v1 schema
    # only carries ``domain_id`` (e.g. ``domain:cortex``), so we derive.
    domain_id = d.get("domain_id") or ""
    plain = _plain_domain(domain_id)
    if plain and plain != _GLOBAL_DOMAIN_TOKEN:
        d["domain"] = plain
        if "isGlobal" not in d:
            d["isGlobal"] = False
    else:
        d["domain"] = "global"
        d["isGlobal"] = True
    # camelCase aliases — card renderers use these
    for snake, camel in _CAMEL_ALIASES.items():
        if snake in d and camel not in d:
            d[camel] = d[snake]
    return d


def _edge_to_dict(e) -> dict[str, Any]:
    d = e.model_dump(exclude_none=True)
    d["type"] = d["kind"]
    return d


def build_workflow_graph(
    store,
    *,
    domain_filter: str | None = None,
    min_memory_heat: float = 0.0,
    memory_limit: int = 0,  # 0 = unbounded (pg_store convention)
    stage: str = "full",
) -> dict[str, Any]:
    """Load sources, build the graph, validate, and return JSON payload.

    The output shape mirrors the legacy ``/api/graph`` response
    (``{nodes, edges, meta}``) so the existing bridge in
    workflow_graph_bridge.js can auto-detect it and route to the new
    renderer.

    Progressive-reveal stages so the first response comes back
    instantly and heavy data streams in as it becomes available:

      * ``skeleton`` — domains, skills, hooks, agents, tool hubs, MCPs,
        memories, discussions, commands. **No file nodes, no AST.**
        This is what the client sees on the very first request.
      * ``files``    — skeleton plus the file nodes derived from
        Claude-session tool events and command-file attribution.
      * ``full``     — everything including AST symbols + edges from
        every indexed AP graph. Used for the final steady-state cache.

    The background enricher in ``http_standalone_graph`` drives this
    sequence: it publishes a skeleton within ~500ms, then republishes
    files, then republishes with AST. The client polls every 4s and
    renders the deltas so projects / files / symbols fade in instead of
    popping in all at once.
    """
    source = WorkflowGraphSource()
    # Skeleton stage is the first paint — it must be lightweight. Only
    # load the L1 structural skeleton (domains + skills + hooks, at
    # most a few dozen nodes). Tool events, agents, commands, memories,
    # discussions, skill / MCP usage, and discussion-scoped relations
    # all stream in as live-tail deltas (``_emit_memory_deltas``,
    # ``_emit_file_deltas``, ``_emit_roster_deltas``) so the first
    # paint lands before the browser ever asks for data.
    if stage == "skeleton":
        skills = source.load_skills()
        hooks = source.load_hooks()
        agents = []
        commands = []
        memories = []
        discussions = []
        skill_usage = []
        mcp_usage = []
        discussion_tools = []
        discussion_agents = []
        discussion_commands = []
        entities = []
        memory_entity_edges = []
    else:
        skills = source.load_skills()
        hooks = source.load_hooks()
        agents = source.load_agent_events()
        commands = source.load_command_events(store)
        memories = source.load_memories(
            store, min_heat=min_memory_heat, limit=memory_limit
        )
        discussions = source.load_discussions()
        skill_usage = source.load_skill_usage()
        mcp_usage = source.load_mcp_usage()
        discussion_tools = source.load_discussion_tool_uses()
        discussion_agents = source.load_discussion_agents()
        discussion_commands = source.load_discussion_commands()
        # Knowledge-graph entities + their memory-link table. Both are
        # bounded by memory-heat (archived / cold memories don't land
        # in the graph, so their links silently drop in
        # ``ingest_about_entity``).
        entities = source.load_entities(store)
        memory_entity_edges = source.load_memory_entity_edges(store)

    # File-derived sources are deferred until ``stage`` reaches files.
    if stage in ("files", "full"):
        tool_events = source.load_tool_events(store)
        discussion_files = source.load_discussion_files()
    else:
        tool_events = []
        discussion_files = []

    known_paths = {e.get("file_path") for e in tool_events if e.get("file_path")}
    command_files = (
        source.load_command_files(store, known_paths)
        if stage in ("files", "full")
        else []
    )

    # AP AST enrichment — loaded synchronously at the ``full`` stage
    # so the WebGL renderer sees every indexed symbol on the first
    # ``/api/graph`` fetch. The Rust/WASM frontend (``/viz``) can
    # absorb 100k+ instanced point-sprites at 60 fps, so the size
    # that used to stall the d3/canvas path is now normal. Empty
    # lists when AP isn't configured — the rest of the builder runs
    # unchanged.
    if stage == "full":
        ast_source = WorkflowGraphASTSource()
        ast_symbols = ast_source.load_symbols([]) if ast_source.enabled() else []
        ast_edges = ast_source.load_ast_edges([]) if ast_source.enabled() else []
    else:
        ast_symbols = []
        ast_edges = []

    if domain_filter:

        def _matches(ev):
            return (ev.get("domain") or "") == domain_filter

        tool_events = [e for e in tool_events if _matches(e)]
        agents = [e for e in agents if _matches(e)]
        commands = [e for e in commands if _matches(e)]
        memories = [m for m in memories if (m.get("domain") or "") == domain_filter]
        discussions = [d for d in discussions if _matches(d)]
        skill_usage = [s for s in skill_usage if _matches(s)]
        mcp_usage = [m for m in mcp_usage if _matches(m)]
        discussion_tools = [e for e in discussion_tools if _matches(e)]
        discussion_agents = [e for e in discussion_agents if _matches(e)]
        entities = [e for e in entities if _matches(e)]

    builder = WorkflowGraphBuilder()
    nodes, edges = builder.build(
        tool_events=tool_events,
        skill_paths=skills,
        hook_defs=hooks,
        agent_events=agents,
        command_events=commands,
        memories=memories,
        discussions=discussions,
        discussion_file_events=discussion_files,
        skill_usage_events=skill_usage,
        command_file_events=command_files,
        mcp_usage_events=mcp_usage,
        discussion_tool_events=discussion_tools,
        discussion_agent_events=discussion_agents,
        discussion_command_events=discussion_commands,
        ast_symbols=ast_symbols,
        ast_edges=ast_edges,
        entities=entities,
        memory_entity_edges=memory_entity_edges,
    )

    validate_graph(nodes, edges)

    domain_count = sum(1 for n in nodes if n.kind == "domain")
    memory_count = sum(1 for n in nodes if n.kind == "memory")
    file_count = sum(1 for n in nodes if n.kind == "file")
    discussion_count = sum(1 for n in nodes if n.kind == "discussion")
    symbol_count = sum(1 for n in nodes if n.kind == "symbol")
    entity_node_count = sum(1 for n in nodes if n.kind == "entity")

    return {
        "nodes": [_node_to_dict(n) for n in nodes],
        "edges": [_edge_to_dict(e) for e in edges],
        "links": [_edge_to_dict(e) for e in edges],
        "meta": {
            "schema": "workflow_graph.v1",
            "domain_filter": domain_filter,
            # Legacy stat-panel keys (polling.js.updateStats reads these).
            "node_count": len(nodes),
            "edge_count": len(edges),
            "domain_count": domain_count,
            "memory_count": memory_count,
            "entity_count": file_count,
            "discussion_count": discussion_count,
            "counts": {
                "nodes": len(nodes),
                "edges": len(edges),
                "tool_events": len(tool_events),
                "skills": len(skills),
                "hooks": len(hooks),
                "agents": len(agents),
                "commands": len(commands),
                "memories": len(memories),
                "discussions": len(discussions),
                "files": file_count,
                "symbols": symbol_count,
                "ast_edges": len(ast_edges),
                "entities": entity_node_count,
                "memory_entity_edges": len(memory_entity_edges),
            },
            # ``ast_source`` is only constructed at the ``full`` stage;
            # earlier stages report ast_enabled based on the env flag
            # so the client can show "enabled, not yet loaded" state.
            "ast_enabled": (
                WorkflowGraphASTSource().enabled()
                if stage == "full"
                else (stage == "full")
            ),
        },
    }


__all__ = ["build_workflow_graph", "GraphValidationError"]
