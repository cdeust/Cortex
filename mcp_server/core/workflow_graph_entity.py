"""Entity-node ingestion for ``WorkflowGraphBuilder`` (Gap 10).

Holds the two helpers that project knowledge-graph entities into the
workflow graph:

  * ``ingest_entity(b, ent)`` — creates one ENTITY node per row from
    ``entities`` table; anchored to its domain via ``IN_DOMAIN`` so
    the schema invariant holds.
  * ``ingest_about_entity(b, link)`` — creates one MEMORY → ENTITY
    ``ABOUT_ENTITY`` edge per row of the ``memory_entities`` join
    table. Silently skips links whose endpoints are not in the graph
    (memories below ``min_heat`` or archived entities).

Split out of ``workflow_graph_builder`` + ``workflow_graph_builder_relational``
to keep both callers under the 300-line ceiling (CLAUDE.md §4.1).

Pure core logic. Imports ``workflow_graph_palette`` + ``workflow_graph_schema``
only — no I/O.
"""

from __future__ import annotations

from mcp_server.core.graph_builder_nodes import ENTITY_COLORS
from mcp_server.core.workflow_graph_schema import (
    EdgeKind,
    NodeIdFactory,
    NodeKind,
    WorkflowEdge,
    edge_provenance_defaults,
)


def _require(rec: dict, key: str, ctx: str):
    """Match the tiny validator the builder and relational modules use —
    duplicated locally so this module has zero cross-module pulls."""
    if key not in rec or rec[key] is None:
        raise ValueError(f"{ctx}: missing key {key!r} in {rec!r}")
    return rec[key]


def ingest_entity(b, ent: dict) -> None:
    """Create one ENTITY node from a knowledge-graph entity row.

    Args:
        b: ``WorkflowGraphBuilder`` instance (for ``_assign_domain`` /
           ``_ensure_domain`` / ``_add_child``).
        ent: ``{"id": int, "name": str, "type": str, "domain": str,
           "heat": float}`` — output of ``workflow_graph_source_pg.
           load_entities``.

    Side effects: adds one ENTITY node + one ``in_domain`` edge.
    """
    pg_id = _require(ent, "id", "entity")
    dom = b._assign_domain(ent.get("domain"))
    b._ensure_domain(dom)
    ent_type = ent.get("type") or "concept"
    heat = float(ent.get("heat") or 0.0)
    b._add_child(
        NodeIdFactory.entity_id(pg_id),
        NodeKind.ENTITY,
        ent.get("name") or f"entity {pg_id}",
        ENTITY_COLORS.get(ent_type, "#50B0C8"),
        dom,
        1.0 + min(3.0, heat * 3.0),
        entityType=ent_type,
        heat=heat,
    )


def ingest_about_entity(b, link: dict) -> None:
    """Create one MEMORY → ENTITY ``ABOUT_ENTITY`` edge.

    ``link`` carries ``memory_id`` + ``entity_id`` (the same PG primary
    keys used by the ``memory_entities`` join table). Silently skips
    when either endpoint is not present in the graph — matches the
    "skip-missing-endpoint" contract of the other relational helpers.
    """
    mem_pg = link.get("memory_id")
    ent_pg = link.get("entity_id")
    if mem_pg is None or ent_pg is None:
        return
    mem_id = NodeIdFactory.memory_id(mem_pg)
    ent_id = NodeIdFactory.entity_id(ent_pg)
    if mem_id not in b._nodes or ent_id not in b._nodes:
        return
    # Gap 6: shared provenance defaults.
    conf, reason = edge_provenance_defaults(EdgeKind.ABOUT_ENTITY.value)
    b._edges.append(
        WorkflowEdge(
            source=mem_id,
            target=ent_id,
            kind=EdgeKind.ABOUT_ENTITY,
            confidence=conf,
            reason=reason,
        )
    )


__all__ = ["ingest_entity", "ingest_about_entity"]
