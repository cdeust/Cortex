"""Relational-edge ingestion for ``WorkflowGraphBuilder``.

These helpers take a ``WorkflowGraphBuilder`` as their first argument
and mutate its ``_nodes`` / ``_edges``. They only run AFTER
``_finalize_files`` because every helper here assumes the file nodes
have been materialised.

Split out of ``workflow_graph_builder`` to keep that file inside the
300-line project ceiling while preserving all existing behaviour — the
builder's ``build`` method still drives the sequence, it just dispatches
to these functions instead of owning the method bodies.
"""

from __future__ import annotations

import logging

from mcp_server.core.workflow_graph_palette import (
    AGENT_COLOR,
    COMMAND_COLOR,
    MCP_COLOR,
    SKILL_COLOR,
    SYMBOL_COLOR_DEFAULT,
    SYMBOL_COLORS,
    primary_tool_color,
)
from mcp_server.core.workflow_graph_schema import (
    EdgeKind,
    NodeIdFactory,
    NodeKind,
    ToolKind,
    WorkflowEdge,
    WorkflowNode,
    edge_provenance_defaults,
)
from mcp_server.core.workflow_graph_schema_enums import PrimaryToolCluster

logger = logging.getLogger(__name__)


def _require(rec: dict, key: str, ctx: str):
    """Mirror of ``workflow_graph_builder._require`` — local copy avoids
    cross-module import flutter."""
    if key not in rec or rec[key] is None:
        raise ValueError(f"{ctx}: missing key {key!r} in {rec!r}")
    return rec[key]


def _as_tool(name: str) -> ToolKind:
    """Parse a tool name; raises ``ValueError`` on unknown."""
    for t in ToolKind:
        if t.value == name or t.value.lower() == name.lower():
            return t
    raise ValueError(f"unknown ToolKind: {name!r}")


def ingest_discussion_file(b, dfe: dict) -> None:
    """Link a discussion to a file (only if both nodes already exist)."""
    sid = str(_require(dfe, "session_id", "discussion_file"))
    path = str(_require(dfe, "file_path", "discussion_file"))
    fid = NodeIdFactory.file_id(path)
    if fid not in b._nodes:
        return
    disc_id = f"discussion:{sid}"
    if disc_id not in b._nodes:
        return
    b._edges.append(
        WorkflowEdge(
            source=disc_id,
            target=fid,
            kind=EdgeKind.DISCUSSION_TOUCHED_FILE,
            weight=float(int(dfe.get("count") or 1)),
        )
    )


def ingest_command_file(b, cfe: dict) -> None:
    """Link a command node to a file node (both must already exist)."""
    h = str(_require(cfe, "cmd_hash", "command_file"))
    path = str(_require(cfe, "file_path", "command_file"))
    cmd_id = NodeIdFactory.command_id(h)
    fid = NodeIdFactory.file_id(path)
    if cmd_id not in b._nodes or fid not in b._nodes:
        return
    b._edges.append(
        WorkflowEdge(
            source=cmd_id,
            target=fid,
            kind=EdgeKind.COMMAND_TOUCHED_FILE,
            weight=float(int(cfe.get("count") or 1)),
        )
    )


def ingest_discussion_tool(b, dte: dict) -> None:
    """Link a discussion to each tool_hub it used; create hub on demand."""
    sid = str(_require(dte, "session_id", "discussion_tool"))
    tool_name = str(_require(dte, "tool", "discussion_tool"))
    dom = b._assign_domain(dte.get("domain"))
    disc_id = f"discussion:{sid}"
    if disc_id not in b._nodes:
        return
    try:
        tool = _as_tool(tool_name)
    except ValueError:
        return
    b._ensure_domain(dom)
    b._build_tool_hubs(dom, [tool])
    hub = NodeIdFactory.tool_hub_id(dom, tool)
    count = int(dte.get("count") or 1)
    b._edges.append(
        WorkflowEdge(
            source=disc_id,
            target=hub,
            kind=EdgeKind.DISCUSSION_USED_TOOL,
            weight=float(count),
        )
    )


def ingest_discussion_agent(b, dae: dict) -> None:
    """Link a discussion to each subagent it spawned; synthesize node if missing."""
    sid = str(_require(dae, "session_id", "discussion_agent"))
    sub = str(_require(dae, "subagent_type", "discussion_agent"))
    dom = b._assign_domain(dae.get("domain"))
    disc_id = f"discussion:{sid}"
    if disc_id not in b._nodes:
        return
    b._ensure_domain(dom)
    agent_id = NodeIdFactory.agent_id(dom, sub)
    if agent_id not in b._nodes:
        b._build_tool_hubs(dom, [ToolKind.TASK])
        b._add_child(
            agent_id,
            NodeKind.AGENT,
            sub,
            AGENT_COLOR,
            dom,
            2.0,
            subagent_type=sub,
            count=0,
        )
    count = int(dae.get("count") or 1)
    b._edges.append(
        WorkflowEdge(
            source=disc_id,
            target=agent_id,
            kind=EdgeKind.DISCUSSION_SPAWNED_AGENT,
            weight=float(count),
        )
    )


def _materialize_discussion_command(
    b, cmd_id: str, cmd: str, h: str, disc_id: str, count0: int
) -> None:
    """Create a minimal command node for a discussion-only Bash invocation."""
    dom = b._nodes[disc_id].domain_id
    b._ensure_domain(dom)
    b._build_tool_hubs(dom, [ToolKind.BASH])
    hub = NodeIdFactory.tool_hub_id(dom, ToolKind.BASH)
    if b._add_child(
        cmd_id,
        NodeKind.COMMAND,
        (cmd or h)[:80],
        COMMAND_COLOR,
        dom,
        1.0 + min(3.0, count0 * 0.1),
        body=cmd or h,
        count=count0,
    ):
        b._edges.append(
            WorkflowEdge(
                source=hub,
                target=cmd_id,
                kind=EdgeKind.COMMAND_IN_HUB,
                weight=float(count0),
            )
        )


def ingest_discussion_command(b, dce: dict) -> None:
    """Link a discussion to each distinct Bash command it ran."""
    sid = str(_require(dce, "session_id", "discussion_command"))
    h = str(_require(dce, "cmd_hash", "discussion_command"))
    cmd = str(dce.get("cmd") or "")
    disc_id = f"discussion:{sid}"
    cmd_id = NodeIdFactory.command_id(h)
    if disc_id not in b._nodes:
        return
    count0 = int(dce.get("count") or 1)
    if cmd_id not in b._nodes:
        _materialize_discussion_command(b, cmd_id, cmd, h, disc_id, count0)
    b._edges.append(
        WorkflowEdge(
            source=disc_id,
            target=cmd_id,
            kind=EdgeKind.DISCUSSION_RAN_COMMAND,
            weight=float(count0),
        )
    )


def ingest_skill_usage(b, sue: dict) -> None:
    """Record a slash-command invocation; expand multi-domain skill membership."""
    name = str(_require(sue, "name", "skill_usage"))
    dom = b._assign_domain(sue.get("domain"))
    b._ensure_domain(dom)
    sid = NodeIdFactory.skill_id(name)
    if sid not in b._nodes:
        b._nodes[sid] = WorkflowNode(
            id=sid,
            kind=NodeKind.SKILL,
            label=name,
            color=SKILL_COLOR,
            domain_id=dom,
            size=2.0,
        )
        b._edges.append(b._in_domain(sid, dom))
    else:
        existing = b._nodes[sid]
        if existing.domain_id != dom and dom not in existing.extra_domain_ids:
            b._nodes[sid] = existing.model_copy(
                update={
                    "extra_domain_ids": list(existing.extra_domain_ids) + [dom],
                }
            )
            b._edges.append(b._in_domain(sid, dom))
    b._edges.append(
        WorkflowEdge(
            source=dom,
            target=sid,
            kind=EdgeKind.INVOKED_SKILL,
            weight=float(int(sue.get("count") or 1)),
        )
    )


def ingest_mcp_usage(b, mue: dict) -> None:
    """Record an MCP-tool invocation; expand multi-domain MCP membership."""
    server = str(_require(mue, "server", "mcp_usage"))
    dom = b._assign_domain(mue.get("domain"))
    b._ensure_domain(dom)
    mcp_id = NodeIdFactory.mcp_id(server)
    tool_name = mue.get("tool") or ""
    count = int(mue.get("count") or 1)
    if mcp_id not in b._nodes:
        b._nodes[mcp_id] = WorkflowNode(
            id=mcp_id,
            kind=NodeKind.MCP,
            label=server,
            color=MCP_COLOR,
            domain_id=dom,
            size=2.2,
            subagent_type=tool_name or None,
            count=count,
        )
        b._edges.append(b._in_domain(mcp_id, dom))
    else:
        existing = b._nodes[mcp_id]
        if dom != existing.domain_id and dom not in existing.extra_domain_ids:
            b._nodes[mcp_id] = existing.model_copy(
                update={
                    "extra_domain_ids": list(existing.extra_domain_ids) + [dom],
                    "count": (existing.count or 0) + count,
                }
            )
            b._edges.append(b._in_domain(mcp_id, dom))
    b._edges.append(
        WorkflowEdge(
            source=dom,
            target=mcp_id,
            kind=EdgeKind.INVOKED_MCP,
            weight=float(count),
            label=tool_name or None,
        )
    )


# ── AST ingestion (ADR-0046) ─────────────────────────────────────────────


def ingest_symbol(b, sym: dict) -> None:
    """Create a SYMBOL node + its DEFINED_IN edge anchoring it to a
    FILE node. Synthesises the parent file node on-demand so AST
    symbols from files Claude Code sessions never touched still show
    up in the graph — this is what ``cortex-visualize`` wants: the
    whole indexed codebase, not just the session-touched slice.
    Idempotent by symbol id."""
    file_path = _require(sym, "file_path", "symbol")
    qname = _require(sym, "qualified_name", "symbol")
    fid = NodeIdFactory.file_id(str(file_path))
    if fid not in b._nodes:
        # Synthesise a minimal file node anchored to the global domain.
        # The builder's ``_finalize_files`` has already run, so we add
        # the file directly; colour via the default file palette.
        b._nodes[fid] = WorkflowNode(
            id=fid,
            kind=NodeKind.FILE,
            label=str(file_path).rsplit("/", 1)[-1],
            color=primary_tool_color(PrimaryToolCluster.READ),
            domain_id=b._GLOBAL_DOMAIN_ID
            if hasattr(b, "_GLOBAL_DOMAIN_ID")
            else "domain:__global__",
            size=0.8,
            path=str(file_path),
            extra_domain_ids=[],
        )
        # Anchor the synthesised file to the global domain so the graph
        # schema invariant (every non-domain node has >= 1 in_domain edge)
        # still holds.
        b._edges.append(
            WorkflowEdge(
                source=fid,
                target=b._nodes[fid].domain_id,
                kind=EdgeKind.IN_DOMAIN,
            )
        )
    sid = NodeIdFactory.symbol_id(str(file_path), str(qname))
    if sid in b._nodes:
        return
    stype = str(sym.get("symbol_type") or "function")
    color = SYMBOL_COLORS.get(stype, SYMBOL_COLOR_DEFAULT)
    parent = b._nodes[fid]
    b._nodes[sid] = WorkflowNode(
        id=sid,
        kind=NodeKind.SYMBOL,
        label=str(qname).rsplit(".", 1)[-1] or str(qname),
        color=color,
        domain_id=parent.domain_id,
        size=0.9,
        symbol_type=stype,
        signature=sym.get("signature"),
        language=sym.get("language"),
        line=sym.get("line"),
        path=str(file_path),
    )
    # Gap 6: defaults from the central provenance table.
    conf, reason = edge_provenance_defaults(EdgeKind.DEFINED_IN.value)
    b._edges.append(
        WorkflowEdge(
            source=sid,
            target=fid,
            kind=EdgeKind.DEFINED_IN,
            confidence=conf,
            reason=reason,
        )
    )


def _resolve_ast_edge_endpoints(b, edge: dict):
    """Resolve (src_id, dst_id, edge_kind) for an AST edge dict, or
    return ``None`` when either endpoint is absent from the builder.

    Contract violations on the emitter side (dst_name must be the exact
    qualified_name used at ``ingest_symbol`` time — Wu audit 2026-04-24)
    log at debug so diagnostics can expose silent drops.
    """
    kind = str(edge.get("kind") or "")
    src_file = str(edge.get("src_file") or "")
    dst_file = str(edge.get("dst_file") or "")
    dst_name = str(edge.get("dst_name") or "")
    if not dst_file or not dst_name:
        return None
    dst_id = NodeIdFactory.symbol_id(dst_file, dst_name)
    if dst_id not in b._nodes:
        logger.debug(
            "ingest_ast_edge drop: no SYMBOL node for dst (%s, %r) kind=%s",
            dst_file,
            dst_name,
            kind,
        )
        return None

    if kind == "imports":
        if not src_file:
            return None
        src_id = NodeIdFactory.file_id(src_file)
        if src_id not in b._nodes:
            logger.debug(
                "ingest_ast_edge drop: no FILE node for IMPORTS src=%s",
                src_file,
            )
            return None
        return src_id, dst_id, EdgeKind.IMPORTS

    src_name = str(edge.get("src_name") or "")
    if not src_file or not src_name:
        return None
    src_id = NodeIdFactory.symbol_id(src_file, src_name)
    if src_id not in b._nodes:
        logger.debug(
            "ingest_ast_edge drop: no SYMBOL node for src (%s, %r) kind=%s",
            src_file,
            src_name,
            kind,
        )
        return None
    edge_kind = EdgeKind.CALLS if kind == "calls" else EdgeKind.MEMBER_OF
    return src_id, dst_id, edge_kind


def ingest_ast_edge(b, edge: dict) -> None:
    """Create a CALLS / IMPORTS / MEMBER_OF edge between two symbols
    (or a file→symbol IMPORTS edge). Skipped silently when either
    endpoint is absent from the graph."""
    resolved = _resolve_ast_edge_endpoints(b, edge)
    if resolved is None:
        return
    src_id, dst_id, edge_kind = resolved
    conf, reason = edge_provenance_defaults(
        edge_kind.value,
        ap_confidence=edge.get("confidence"),
        ap_reason=edge.get("reason"),
    )
    b._edges.append(
        WorkflowEdge(
            source=src_id,
            target=dst_id,
            kind=edge_kind,
            confidence=conf,
            reason=reason,
        )
    )


# ``ingest_about_entity`` lives in ``workflow_graph_entity.py`` alongside
# ``ingest_entity`` — grouped by concept (knowledge-graph entities) so
# the MEMORY→ENTITY wiring stays in one file.
