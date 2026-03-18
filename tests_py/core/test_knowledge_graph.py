"""Tests for mcp_server.core.knowledge_graph — entity extraction and relationships."""

from mcp_server.core.knowledge_graph import (
    extract_entities,
    detect_co_occurrences,
    infer_relationships,
)


class TestExtractEntities:
    def test_import_extraction(self):
        content = "from mcp_server.core import thermodynamics"
        entities = extract_entities(content)
        names = [e["name"] for e in entities]
        assert "mcp_server.core" in names
        assert "thermodynamics" in names

    def test_full_import(self):
        content = "import numpy"
        entities = extract_entities(content)
        assert any(e["name"] == "numpy" and e["type"] == "dependency" for e in entities)

    def test_function_def_extraction(self):
        content = "def compute_surprise(content, similarities):\n    pass"
        entities = extract_entities(content)
        assert any(
            e["name"] == "compute_surprise" and e["type"] == "function"
            for e in entities
        )

    def test_class_extraction(self):
        content = "class MemoryStore:\n    pass"
        entities = extract_entities(content)
        assert any(e["name"] == "MemoryStore" for e in entities)

    def test_error_fix_pattern(self):
        content = "Fixed the RuntimeError in the parser"
        entities = extract_entities(content)
        assert any(
            e["type"] == "error" and e["relationship_context"] == "resolved_by"
            for e in entities
        )

    def test_decision_pattern(self):
        content = "decided to use PostgreSQL instead of MySQL"
        entities = extract_entities(content)
        assert any(e["type"] == "decision" for e in entities)

    def test_file_path_extraction(self):
        content = "Check src/core/module.py for details"
        entities = extract_entities(content)
        assert any(e["type"] == "file" for e in entities)

    def test_camelcase_extraction(self):
        content = "The EmbeddingEngine handles vector encoding"
        entities = extract_entities(content)
        assert any(e["name"] == "EmbeddingEngine" for e in entities)

    def test_deduplication(self):
        content = "import numpy\nimport numpy"
        entities = extract_entities(content)
        numpy_entities = [e for e in entities if e["name"] == "numpy"]
        assert len(numpy_entities) == 1

    def test_empty_content(self):
        assert extract_entities("") == []

    def test_plain_text(self):
        entities = extract_entities("The weather is nice today")
        # Should not extract anything meaningful
        assert all(e["type"] != "dependency" for e in entities)


class TestDetectCoOccurrences:
    def test_nearby_entities(self):
        content = "Python and PostgreSQL are great together"
        results = detect_co_occurrences(["Python", "PostgreSQL"], content)
        assert len(results) == 1
        assert results[0][2] > 0  # Positive proximity

    def test_distant_entities(self):
        content = "Python " + "x " * 500 + "PostgreSQL"
        results = detect_co_occurrences(
            ["Python", "PostgreSQL"], content, window_chars=100
        )
        assert len(results) == 0  # Too far apart

    def test_no_entities_found(self):
        content = "nothing relevant here"
        results = detect_co_occurrences(["Python", "PostgreSQL"], content)
        assert len(results) == 0

    def test_multiple_pairs(self):
        content = "Python uses PostgreSQL and Redis together"
        results = detect_co_occurrences(["Python", "PostgreSQL", "Redis"], content)
        assert len(results) >= 2


class TestInferRelationships:
    def test_import_relationship(self):
        entities = [
            {"name": "numpy", "type": "dependency", "relationship_context": ""},
            {"name": "array", "type": "function", "relationship_context": "imports"},
        ]
        rels = infer_relationships(entities)
        assert any(r["type"] == "imports" for r in rels)

    def test_decision_relationship(self):
        entities = [
            {
                "name": "PostgreSQL",
                "type": "decision",
                "relationship_context": "decided_to_use",
            },
            {
                "name": "MySQL",
                "type": "decision",
                "relationship_context": "decided_to_use",
            },
        ]
        rels = infer_relationships(entities)
        assert any(r["type"] == "decided_to_use" for r in rels)

    def test_error_relationship(self):
        entities = [
            {
                "name": "RuntimeError",
                "type": "error",
                "relationship_context": "resolved_by",
            },
        ]
        rels = infer_relationships(entities)
        assert any(r["type"] == "resolved_by" for r in rels)

    def test_empty_entities(self):
        assert infer_relationships([]) == []
