"""Unit tests for the ``confidence`` + ``reason`` fields on WorkflowEdge
(Gap 6).

Verifies:

  * Defaults: edges without explicit values carry ``None`` for both
    fields, so adding the fields is backward-compatible.
  * Range: ``confidence`` is a float in [0.0, 1.0] (validated by
    pydantic's ``float | None``; no explicit constraint but producers
    must stay in-range — tested indirectly via the ingestors).
  * ``defined_in`` (from ``ingest_symbol``) carries confidence=1.0 +
    reason="direct-ast" — structural AST fact.
  * ``about_entity`` (from ``ingest_about_entity``) carries
    confidence=1.0 + reason="memory-entities-link".
  * ``ingest_ast_edge`` propagates AP-supplied confidence + reason
    verbatim for calls / imports, defaults ``member_of`` to 1.0 +
    "direct-ast" when AP doesn't emit a value.
  * The schema accepts ``confidence: None`` (legacy edges).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mcp_server.core.workflow_graph_builder import WorkflowGraphBuilder
from mcp_server.core.workflow_graph_builder_relational import (
    ingest_ast_edge,
    ingest_symbol,
)
from mcp_server.core.workflow_graph_inputs import WorkflowBuildInputs
from mcp_server.core.workflow_graph_schema import (
    EdgeKind,
    NodeIdFactory,
    WorkflowEdge,
    edge_provenance_defaults,
    validate_graph,
)


class TestWorkflowEdgeSchema:
    def test_defaults_none(self):
        e = WorkflowEdge(source="a:1", target="a:2", kind=EdgeKind.IN_DOMAIN)
        assert e.confidence is None
        assert e.reason is None

    def test_explicit_values_round_trip(self):
        e = WorkflowEdge(
            source="a:1",
            target="a:2",
            kind=EdgeKind.CALLS,
            confidence=0.9,
            reason="import-scope-lookup",
        )
        assert e.confidence == 0.9
        assert e.reason == "import-scope-lookup"


class TestDefinedInEdge:
    def test_symbol_ingest_tags_defined_in_as_direct_ast(self):
        b = WorkflowGraphBuilder()
        # Bootstrap a domain so _assign_domain doesn't fail for FILE.
        b.build(WorkflowBuildInputs())
        ingest_symbol(
            b,
            {
                "file_path": "mod/foo.py",
                "qualified_name": "mod/foo.py::bar",
                "symbol_type": "function",
            },
        )
        sid = NodeIdFactory.symbol_id("mod/foo.py", "mod/foo.py::bar")
        fid = NodeIdFactory.file_id("mod/foo.py")
        defined_in = [
            e
            for e in b._edges
            if e.source == sid
            and e.target == fid
            and e.kind == EdgeKind.DEFINED_IN.value
        ]
        assert len(defined_in) == 1
        assert defined_in[0].confidence == 1.0
        assert defined_in[0].reason == "direct-ast"


class TestAstEdgeIngest:
    def _prime_two_symbols(self):
        b = WorkflowGraphBuilder()
        b.build(WorkflowBuildInputs())
        ingest_symbol(
            b,
            {
                "file_path": "a.py",
                "qualified_name": "a.py::caller",
                "symbol_type": "function",
            },
        )
        ingest_symbol(
            b,
            {
                "file_path": "a.py",
                "qualified_name": "a.py::callee",
                "symbol_type": "function",
            },
        )
        return b

    def test_calls_preserves_ap_confidence_and_reason(self):
        b = self._prime_two_symbols()
        ingest_ast_edge(
            b,
            {
                "kind": "calls",
                "src_file": "a.py",
                "src_name": "a.py::caller",
                "dst_file": "a.py",
                "dst_name": "a.py::callee",
                "confidence": 0.9,
                "reason": "import-scope-lookup",
            },
        )
        calls = [e for e in b._edges if e.kind == EdgeKind.CALLS.value]
        assert len(calls) == 1
        assert calls[0].confidence == 0.9
        assert calls[0].reason == "import-scope-lookup"

    def test_calls_without_ap_metadata_leaves_fields_none(self):
        b = self._prime_two_symbols()
        ingest_ast_edge(
            b,
            {
                "kind": "calls",
                "src_file": "a.py",
                "src_name": "a.py::caller",
                "dst_file": "a.py",
                "dst_name": "a.py::callee",
            },
        )
        calls = [e for e in b._edges if e.kind == EdgeKind.CALLS.value]
        assert calls[0].confidence is None
        assert calls[0].reason is None

    def test_member_of_defaults_to_direct_ast_when_ap_silent(self):
        b = self._prime_two_symbols()
        ingest_ast_edge(
            b,
            {
                "kind": "member_of",
                "src_file": "a.py",
                "src_name": "a.py::caller",
                "dst_file": "a.py",
                "dst_name": "a.py::callee",
            },
        )
        m = [e for e in b._edges if e.kind == EdgeKind.MEMBER_OF.value]
        assert m[0].confidence == 1.0
        assert m[0].reason == "direct-ast"


class TestValidationWithConfidence:
    def test_validate_graph_accepts_mixed_confidence_edges(self):
        """Invariants still pass when some edges carry confidence + others don't."""
        b = WorkflowGraphBuilder()
        nodes, edges = b.build(
            WorkflowBuildInputs(
                entities=[
                    {
                        "id": 1,
                        "name": "X",
                        "type": "concept",
                        "domain": "d",
                        "heat": 0.3,
                    }
                ],
            )
        )
        validate_graph(nodes, edges)


class TestConfidenceRangeConstraint:
    """Gap 6 review fix (Dijkstra concern): pydantic rejects values
    outside [0.0, 1.0] so a buggy producer can never emit 1.5 or
    -0.3 and have it reach the renderer."""

    def test_confidence_above_one_rejected(self):
        with pytest.raises(ValidationError):
            WorkflowEdge(
                source="a:1",
                target="a:2",
                kind=EdgeKind.CALLS,
                confidence=1.5,
            )

    def test_confidence_below_zero_rejected(self):
        with pytest.raises(ValidationError):
            WorkflowEdge(
                source="a:1",
                target="a:2",
                kind=EdgeKind.CALLS,
                confidence=-0.1,
            )

    def test_confidence_at_bounds_accepted(self):
        WorkflowEdge(
            source="a:1",
            target="a:2",
            kind=EdgeKind.CALLS,
            confidence=0.0,
        )
        WorkflowEdge(
            source="a:1",
            target="a:2",
            kind=EdgeKind.CALLS,
            confidence=1.0,
        )


class TestEdgeProvenanceDefaults:
    """Gap 6 review fix (Dijkstra DRY): single source of truth for
    structural defaults + empty-string parity between paths."""

    def test_structural_kind_defaults_applied(self):
        assert edge_provenance_defaults("defined_in") == (1.0, "direct-ast")
        assert edge_provenance_defaults("member_of") == (1.0, "direct-ast")
        assert edge_provenance_defaults("about_entity") == (
            1.0,
            "memory-entities-link",
        )

    def test_heuristic_kind_preserves_ap_values(self):
        assert edge_provenance_defaults(
            "calls", ap_confidence=0.9, ap_reason="import-scope-lookup"
        ) == (0.9, "import-scope-lookup")

    def test_empty_reason_normalizes_to_none_for_heuristic_kinds(self):
        """Cross-path parity: an AP-supplied empty string must become
        None regardless of which ingest path produces the edge."""
        conf, reason = edge_provenance_defaults(
            "calls", ap_confidence=0.5, ap_reason=""
        )
        assert reason is None
        assert conf == 0.5

    def test_heuristic_without_ap_metadata_stays_none(self):
        assert edge_provenance_defaults("calls") == (None, None)
        assert edge_provenance_defaults("imports") == (None, None)

    def test_ap_confidence_of_zero_is_preserved_not_defaulted(self):
        """A legitimate AP confidence of exactly 0.0 is information —
        ``edge_provenance_defaults`` must NOT treat it as 'missing' and
        silently overwrite it with a structural default."""
        conf, _ = edge_provenance_defaults(
            "calls", ap_confidence=0.0, ap_reason="heuristic"
        )
        assert conf == 0.0
