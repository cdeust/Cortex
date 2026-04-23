"""Unit tests for NodeKind.ENTITY wiring in the workflow graph.

Verifies the contract documented in
``mcp_server/core/workflow_graph_schema_enums.py``:

  * ``_ingest_entity`` produces exactly one ENTITY node per input row.
  * Each ENTITY node carries an ``in_domain`` edge to its domain hub
    (satisfying ``_check_in_domain_counts``).
  * ``ingest_about_entity`` produces one MEMORY→ENTITY edge per
    ``memory_entities`` join row whose endpoints are both in the graph.
  * Orphan links (missing memory or entity) are silently dropped.
  * ``validate_graph`` accepts the resulting graph.
"""

from __future__ import annotations

import pytest

from mcp_server.core.workflow_graph_builder import WorkflowGraphBuilder
from mcp_server.core.workflow_graph_inputs import WorkflowBuildInputs
from mcp_server.core.workflow_graph_schema import (
    EdgeKind,
    NodeIdFactory,
    NodeKind,
    validate_graph,
)


def _build(**kwargs):
    """Construct WorkflowBuildInputs from kwargs and run the builder."""
    b = WorkflowGraphBuilder()
    return b.build(
        WorkflowBuildInputs(
            memories=kwargs.pop("memories", []),
            entities=kwargs.pop("entities", []),
            memory_entity_edges=kwargs.pop("memory_entity_edges", []),
        )
    )


class TestEntityNodeIngestion:
    def test_entity_row_becomes_entity_node(self):
        nodes, _edges = _build(
            entities=[
                {
                    "id": 7,
                    "name": "pgvector",
                    "type": "technology",
                    "domain": "cortex",
                    "heat": 0.5,
                }
            ]
        )
        entity_nodes = [n for n in nodes if n.kind == NodeKind.ENTITY.value]
        assert len(entity_nodes) == 1
        node = entity_nodes[0]
        assert node.id == NodeIdFactory.entity_id(7)
        assert node.label == "pgvector"

    def test_entity_node_has_exactly_one_in_domain_edge(self):
        nodes, edges = _build(
            entities=[
                {
                    "id": 7,
                    "name": "pgvector",
                    "type": "technology",
                    "domain": "cortex",
                    "heat": 0.5,
                }
            ]
        )
        eid = NodeIdFactory.entity_id(7)
        in_domain = [
            e for e in edges if e.source == eid and e.kind == EdgeKind.IN_DOMAIN.value
        ]
        assert len(in_domain) == 1
        # And the graph as a whole passes validation.
        validate_graph(nodes, edges)

    def test_heat_scales_entity_size(self):
        nodes, _ = _build(
            entities=[
                {"id": 1, "name": "cold", "type": "concept", "domain": "", "heat": 0.0},
                {"id": 2, "name": "hot", "type": "concept", "domain": "", "heat": 1.0},
            ]
        )
        sizes = {n.label: n.size for n in nodes if n.kind == NodeKind.ENTITY.value}
        assert sizes["hot"] > sizes["cold"]


class TestAboutEntityEdge:
    def test_memory_entity_link_emits_about_entity_edge(self):
        nodes, edges = _build(
            memories=[
                {
                    "id": 42,
                    "domain": "cortex",
                    "consolidation_stage": "episodic",
                    "heat": 0.6,
                    "content": "we chose pgvector over faiss",
                }
            ],
            entities=[
                {
                    "id": 7,
                    "name": "pgvector",
                    "type": "technology",
                    "domain": "cortex",
                    "heat": 0.5,
                }
            ],
            memory_entity_edges=[{"memory_id": 42, "entity_id": 7}],
        )
        about = [e for e in edges if e.kind == EdgeKind.ABOUT_ENTITY.value]
        assert len(about) == 1
        assert about[0].source == NodeIdFactory.memory_id(42)
        assert about[0].target == NodeIdFactory.entity_id(7)
        validate_graph(nodes, edges)

    def test_orphan_link_is_dropped_silently(self):
        """Link to a missing memory (e.g., below heat threshold) must
        not create an edge, and the graph must still validate."""
        nodes, edges = _build(
            entities=[
                {
                    "id": 7,
                    "name": "pgvector",
                    "type": "technology",
                    "domain": "cortex",
                    "heat": 0.5,
                }
            ],
            memory_entity_edges=[{"memory_id": 9999, "entity_id": 7}],
        )
        about = [e for e in edges if e.kind == EdgeKind.ABOUT_ENTITY.value]
        assert about == []
        validate_graph(nodes, edges)

    def test_missing_entity_endpoint_is_dropped(self):
        nodes, edges = _build(
            memories=[
                {
                    "id": 42,
                    "domain": "cortex",
                    "consolidation_stage": "episodic",
                    "heat": 0.6,
                    "content": "mem",
                }
            ],
            memory_entity_edges=[{"memory_id": 42, "entity_id": 9999}],
        )
        about = [e for e in edges if e.kind == EdgeKind.ABOUT_ENTITY.value]
        assert about == []
        validate_graph(nodes, edges)

    def test_none_ids_are_skipped(self):
        nodes, edges = _build(
            memory_entity_edges=[
                {"memory_id": None, "entity_id": 7},
                {"memory_id": 42, "entity_id": None},
            ],
        )
        about = [e for e in edges if e.kind == EdgeKind.ABOUT_ENTITY.value]
        assert about == []
        validate_graph(nodes, edges)


class TestEntityIngestValidation:
    def test_entity_without_id_raises(self):
        """An entity row missing the mandatory ``id`` key must raise a
        ValueError in ``_require`` — no silent node without a stable
        id, since the whole downstream pipeline keys on
        ``NodeIdFactory.entity_id(id)``.
        """
        with pytest.raises(ValueError, match="entity: missing key 'id'"):
            _build(
                entities=[
                    {
                        "name": "orphan",
                        "type": "concept",
                        "domain": "cortex",
                        "heat": 0.5,
                    }
                ]
            )
