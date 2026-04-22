"""Workflow graph schema: nodes and edges for the Claude-workflow rewrite.

Each project/domain becomes a brain-region cloud; nodes inside a cloud
cluster by the Claude Code surface that produced them (skills, hooks,
agents, tools, files, memories, discussions, entities).

Generative invariants (enforced by ``validate_graph``):
  * Node IDs are deterministic (NodeIdFactory) and prefixed by NodeKind.
  * Every non-domain node has exactly one ``in_domain`` edge, except
    ``file`` nodes, which may span multiple domains (>=1 in_domain edge).
  * ``tool_hub`` nodes exist at exactly one per (domain, tool) pair.
  * File colors follow the primary-tool meta-rule
    (Edit/Write > Read > Grep/Glob > Bash) -- the single rule that
    resolves a file touched by several tools.

Pure core logic. Imports stdlib + pydantic + the workflow-graph enum /
palette modules only. No I/O.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

# Re-export enums + palette so existing callers (handlers, builder,
# tests) keep importing from ``workflow_graph_schema`` unchanged.
from mcp_server.core.workflow_graph_schema_enums import (
    EdgeKind,
    NodeKind,
    PrimaryToolCluster,
    ToolKind,
)

GLOBAL_DOMAIN_ID = "domain:__global__"


# ── Pydantic v2 models ─────────────────────────────────────────────────


class WorkflowNode(BaseModel):
    """A node in the workflow graph, ready for D3 rendering.

    ``extra="allow"`` lets callers attach scientific measurement fields
    (heat_base, surprise_score, importance, arousal, plasticity, …) that
    the Knowledge and Board card renderers surface verbatim. Adding them
    as explicit schema attributes would ossify the schema — the memory
    table gains instruments faster than this model can chase.
    """

    model_config = ConfigDict(extra="allow", use_enum_values=True)

    id: str
    kind: NodeKind
    label: str = ""
    color: str = "#999999"
    domain_id: str = ""
    size: float = 1.0
    tool: ToolKind | None = None
    primary_cluster: PrimaryToolCluster | None = None
    path: str | None = None
    stage: str | None = None
    extra_domain_ids: list[str] = Field(default_factory=list)
    body: str | None = None
    session_id: str | None = None
    heat: float | None = None
    tags: list[str] = Field(default_factory=list)
    count: int | None = None
    event: str | None = None
    subagent_type: str | None = None
    created_at: str | None = None
    # AST-derived fields (ADR-0046, populated by the automatised-pipeline
    # bridge). ``symbol_type`` is one of function/class/module/import;
    # ``signature`` is the source-captured function signature;
    # ``language`` is rust/python/typescript; ``line`` is 1-based source
    # location in the parent file.
    symbol_type: str | None = None
    signature: str | None = None
    language: str | None = None
    line: int | None = None


class WorkflowEdge(BaseModel):
    """A directed edge in the workflow graph."""

    model_config = ConfigDict(extra="ignore", use_enum_values=True)

    source: str
    target: str
    kind: EdgeKind
    weight: float = 1.0
    label: str | None = None


# ── Deterministic ID factory ───────────────────────────────────────────


def _short_hash(value: str, width: int = 10) -> str:
    """Stable, non-cryptographic short hash for ID stability across runs."""
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:width]


class NodeIdFactory:
    """Deterministic node-id minting. Same input -> same id across runs."""

    @staticmethod
    def domain_id(project: str | None) -> str:
        return f"domain:{project}" if project else GLOBAL_DOMAIN_ID

    @staticmethod
    def tool_hub_id(domain_id: str, tool: ToolKind) -> str:
        return f"tool_hub:{domain_id}:{tool.value}"

    @staticmethod
    def file_id(abs_path: str) -> str:
        return f"file:{_short_hash(abs_path)}"

    @staticmethod
    def skill_id(name: str) -> str:
        clean = name.lstrip("/").strip() or "unknown"
        return f"skill:{clean}"

    @staticmethod
    def hook_id(event_name: str, script_path: str) -> str:
        return f"hook:{event_name}:{_short_hash(script_path)}"

    @staticmethod
    def agent_id(domain_id: str, agent_type: str) -> str:
        return f"agent:{domain_id}:{agent_type}"

    @staticmethod
    def command_id(cmd_hash: str) -> str:
        return f"command:{cmd_hash}"

    @staticmethod
    def memory_id(pg_id: str | int) -> str:
        return f"memory:{pg_id}"

    @staticmethod
    def mcp_id(server_name: str) -> str:
        return f"mcp:{server_name}"

    @staticmethod
    def symbol_id(file_abs_path: str, qualified_name: str) -> str:
        """Stable id across indexing runs: hash of ``<file>::<qualified>``.

        ``qualified_name`` is AP's fully-qualified symbol name
        (``module.ClassName.method``). Including the file disambiguates
        identical names across modules in different languages.
        """
        key = f"{file_abs_path}::{qualified_name}"
        return f"symbol:{_short_hash(key, width=12)}"


# ── Validation (meta-rules that decide well-formedness) ────────────────


class GraphValidationError(ValueError):
    """Raised when the generative rules reject the graph."""


def _nk(v: object) -> NodeKind:
    return v if isinstance(v, NodeKind) else NodeKind(v)


def _split_tool_hub_id(node_id: str) -> tuple[str, str]:
    if not node_id.startswith("tool_hub:") or node_id.count(":") < 2:
        raise GraphValidationError(f"malformed tool_hub id: {node_id}")
    inner, tool = node_id.split(":", 1)[1].rsplit(":", 1)
    return inner, tool


_MULTI_DOMAIN_KINDS = (NodeKind.FILE, NodeKind.MCP, NodeKind.SKILL)


def _check_unique_ids_and_prefix(
    node_list: list[WorkflowNode],
) -> dict[str, WorkflowNode]:
    """Invariant 1+5: unique ids, and id prefix matches node kind."""
    seen: dict[str, WorkflowNode] = {}
    for node in node_list:
        if node.id in seen:
            raise GraphValidationError(f"duplicate node id: {node.id}")
        seen[node.id] = node
        kind = _nk(node.kind)
        if not node.id.startswith(f"{kind.value}:"):
            raise GraphValidationError(
                f"node id {node.id!r} does not match kind {kind.value}"
            )
    return seen


def _check_edge_endpoints(
    edge_list: list[WorkflowEdge], seen: dict[str, WorkflowNode]
) -> None:
    """Invariant 2: every edge source and target resolves to a node."""
    for edge in edge_list:
        if edge.source not in seen:
            raise GraphValidationError(f"edge source missing: {edge.source}")
        if edge.target not in seen:
            raise GraphValidationError(f"edge target missing: {edge.target}")


def _count_in_domain(edge_list: list[WorkflowEdge]) -> Counter[str]:
    """Source-side counts of ``in_domain`` edges, keyed by source id."""
    counts: Counter[str] = Counter()
    for edge in edge_list:
        ek = edge.kind if isinstance(edge.kind, EdgeKind) else EdgeKind(edge.kind)
        if ek is EdgeKind.IN_DOMAIN:
            counts[edge.source] += 1
    return counts


def _check_in_domain_counts(
    node_list: list[WorkflowNode], in_domain_counts: Counter[str]
) -> None:
    """Invariant 3: exactly one in_domain edge per non-domain node
    (≥1 for file/mcp/skill). SYMBOL nodes (ADR-0046) are exempt — they
    are anchored to their parent FILE via a DEFINED_IN edge instead
    of a domain edge, which is enforced by ``_check_symbol_anchor``."""
    for node in node_list:
        kind = _nk(node.kind)
        if kind is NodeKind.DOMAIN or kind is NodeKind.SYMBOL:
            continue
        count = in_domain_counts.get(node.id, 0)
        if kind in _MULTI_DOMAIN_KINDS:
            if count < 1:
                raise GraphValidationError(
                    f"{kind.value} node {node.id} has no in_domain edge"
                )
        elif count != 1:
            raise GraphValidationError(
                f"node {node.id} ({kind.value}) must have exactly one "
                f"in_domain edge, got {count}"
            )


def _check_symbol_anchor(
    node_list: list[WorkflowNode], edge_list: list[WorkflowEdge]
) -> None:
    """Invariant 6 (AST): every SYMBOL node must have at least one
    DEFINED_IN edge pointing to a FILE node. Without that anchor the
    layout has nowhere to place the symbol inside its file cluster."""
    file_ids = {n.id for n in node_list if _nk(n.kind) is NodeKind.FILE}
    anchors: Counter[str] = Counter()
    for edge in edge_list:
        ek = edge.kind if isinstance(edge.kind, EdgeKind) else EdgeKind(edge.kind)
        if ek is EdgeKind.DEFINED_IN and edge.target in file_ids:
            anchors[edge.source] += 1
    for node in node_list:
        if _nk(node.kind) is not NodeKind.SYMBOL:
            continue
        if anchors.get(node.id, 0) < 1:
            raise GraphValidationError(
                f"symbol node {node.id} has no defined_in edge to a file"
            )


def _check_tool_hub_pairs(node_list: list[WorkflowNode]) -> None:
    """Invariant 4: tool_hub ids reference known domain + tool, unique per pair."""
    domain_ids = {n.id for n in node_list if _nk(n.kind) is NodeKind.DOMAIN}
    known_tools = {t.value for t in ToolKind}
    pair_counts: Counter[tuple[str, str]] = Counter()
    for node in node_list:
        if _nk(node.kind) is not NodeKind.TOOL_HUB:
            continue
        inner_domain, tool_value = _split_tool_hub_id(node.id)
        if inner_domain not in domain_ids:
            raise GraphValidationError(
                f"tool_hub {node.id} references unknown domain {inner_domain}"
            )
        if tool_value not in known_tools:
            raise GraphValidationError(
                f"tool_hub {node.id} has unknown tool {tool_value}"
            )
        pair_counts[(inner_domain, tool_value)] += 1
    for pair, count in pair_counts.items():
        if count > 1:
            raise GraphValidationError(
                f"duplicate tool_hub for (domain={pair[0]}, tool={pair[1]}): {count}"
            )


def validate_graph(
    nodes: Iterable[WorkflowNode],
    edges: Iterable[WorkflowEdge],
) -> None:
    """Enforce generative invariants. Raises ``GraphValidationError``.

    Invariants:
      1. Unique node ids            → ``_check_unique_ids_and_prefix``
      2. Edge endpoints resolve     → ``_check_edge_endpoints``
      3. ``in_domain`` counts       → ``_check_in_domain_counts``
      4. tool_hub well-formedness   → ``_check_tool_hub_pairs``
      5. id prefix matches kind     → ``_check_unique_ids_and_prefix``
      6. symbol has ≥1 defined_in   → ``_check_symbol_anchor`` (ADR-0046)
    """
    node_list = list(nodes)
    edge_list = list(edges)
    seen = _check_unique_ids_and_prefix(node_list)
    _check_edge_endpoints(edge_list, seen)
    _check_in_domain_counts(node_list, _count_in_domain(edge_list))
    _check_tool_hub_pairs(node_list)
    _check_symbol_anchor(node_list, edge_list)


# ``__all__`` intentionally omitted: every symbol imported above is
# re-exported by being in the module namespace, and the explicit list
# would duplicate what imports already encode.
