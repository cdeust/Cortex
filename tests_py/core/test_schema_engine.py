"""Tests for schema_engine — cortical knowledge structures."""

from mcp_server.core.schema_engine import (
    compute_schema_match,
    classify_schema_match,
    find_best_matching_schema,
    accommodate_schema,
    should_revise_schema,
    generate_predictions,
    compute_prediction_error,
    compute_schema_free_energy,
)
from mcp_server.core.schema_extraction import (
    Schema,
    extract_schema_from_cluster,
    should_merge_schemas,
    merge_schemas,
    schema_to_dict,
    schema_from_dict,
)


def _make_memories(
    n: int, common_entities: list[str], common_tags: list[str]
) -> list[dict]:
    """Create a cluster of memories sharing common entities and tags."""
    return [
        {
            "entities": common_entities + [f"unique_{i}"],
            "tags": common_tags,
            "relationships": [],
        }
        for i in range(n)
    ]


class TestSchemaFormation:
    def test_forms_from_cluster(self):
        mems = _make_memories(6, ["React", "useState", "component"], ["frontend"])
        schema = extract_schema_from_cluster(mems, domain="frontend", schema_id="s1")
        assert schema is not None
        assert "React" in schema.entity_signature
        assert schema.formation_count == 6

    def test_rejects_small_cluster(self):
        mems = _make_memories(2, ["foo"], ["bar"])
        schema = extract_schema_from_cluster(mems, min_memories=5)
        assert schema is None

    def test_filters_infrequent_entities(self):
        mems = _make_memories(10, ["core_entity"], ["tag"])
        # Add one memory with a rare entity
        mems.append({"entities": ["rare_entity"], "tags": ["tag"], "relationships": []})
        schema = extract_schema_from_cluster(mems, schema_id="s1", min_memories=5)
        assert schema is not None
        assert "core_entity" in schema.entity_signature
        assert "rare_entity" not in schema.entity_signature

    def test_generates_label(self):
        mems = _make_memories(5, ["Foo", "Bar", "Baz"], ["test"])
        schema = extract_schema_from_cluster(mems, schema_id="s1")
        assert schema is not None
        assert len(schema.label) > 0


class TestSchemaMatching:
    def test_high_match_for_consistent_memory(self):
        schema = Schema(
            entity_signature={"React": 0.9, "useState": 0.8, "component": 0.7},
            tag_signature={"frontend": 0.9},
        )
        score = compute_schema_match(["React", "useState"], ["frontend"], schema)
        assert score >= 0.5

    def test_low_match_for_inconsistent_memory(self):
        schema = Schema(
            entity_signature={"React": 0.9, "useState": 0.8},
            tag_signature={"frontend": 0.9},
        )
        score = compute_schema_match(["Django", "ORM"], ["backend"], schema)
        assert score < 0.3

    def test_classification(self):
        assert classify_schema_match(0.8) == "assimilate"
        assert classify_schema_match(0.5) == "normal"
        assert classify_schema_match(0.1) == "accommodate"

    def test_find_best_schema(self):
        s1 = Schema(schema_id="s1", entity_signature={"React": 0.9})
        s2 = Schema(schema_id="s2", entity_signature={"Django": 0.9})
        best, score = find_best_matching_schema(["React"], [], [s1, s2])
        assert best is not None
        assert best.schema_id == "s1"

    def test_no_match_returns_none(self):
        s1 = Schema(schema_id="s1", entity_signature={"React": 0.9})
        best, score = find_best_matching_schema(["Haskell"], [], [s1])
        assert best is None


class TestAccommodation:
    def test_adds_new_entities(self):
        schema = Schema(entity_signature={"foo": 0.8, "bar": 0.6})
        updated = accommodate_schema(schema, ["foo", "new_entity"], [])
        assert "new_entity" in updated.entity_signature

    def test_decays_unseen_entities(self):
        schema = Schema(entity_signature={"foo": 0.8, "bar": 0.1})
        updated = accommodate_schema(schema, ["foo"], [])
        assert updated.entity_signature.get("bar", 0) < 0.1

    def test_increments_violation_count(self):
        schema = Schema(violation_count=5)
        updated = accommodate_schema(schema, ["x"], [])
        assert updated.violation_count == 6

    def test_preserves_immutable_fields(self):
        schema = Schema(schema_id="s1", domain="test", formation_count=10)
        updated = accommodate_schema(schema, ["x"], [])
        assert updated.schema_id == "s1"
        assert updated.domain == "test"
        assert updated.formation_count == 10


class TestRevision:
    def test_revision_triggered_by_violations(self):
        schema = Schema(violation_count=15, formation_count=10, assimilation_count=10)
        assert should_revise_schema(schema) is True

    def test_no_revision_with_few_violations(self):
        schema = Schema(violation_count=2, formation_count=100, assimilation_count=100)
        assert should_revise_schema(schema) is False

    def test_revision_triggered_by_ratio(self):
        schema = Schema(violation_count=5, formation_count=5, assimilation_count=5)
        assert should_revise_schema(schema) is True  # 50% violation ratio


class TestMerging:
    def test_similar_schemas_should_merge(self):
        s1 = Schema(entity_signature={"A": 0.8, "B": 0.7, "C": 0.6})
        s2 = Schema(entity_signature={"A": 0.9, "B": 0.8, "C": 0.5})  # 100% overlap
        assert should_merge_schemas(s1, s2) is True

    def test_different_schemas_should_not_merge(self):
        s1 = Schema(entity_signature={"A": 0.8, "B": 0.7})
        s2 = Schema(entity_signature={"X": 0.9, "Y": 0.8})
        assert should_merge_schemas(s1, s2) is False

    def test_merge_combines_signatures(self):
        s1 = Schema(schema_id="s1", entity_signature={"A": 0.8}, formation_count=5)
        s2 = Schema(schema_id="s2", entity_signature={"B": 0.6}, formation_count=5)
        merged = merge_schemas(s1, s2, merged_id="m1")
        assert "A" in merged.entity_signature
        assert "B" in merged.entity_signature
        assert merged.formation_count == 10
        assert merged.violation_count == 0  # Reset on merge


class TestPredictions:
    def test_generate_predictions(self):
        schema = Schema(entity_signature={"foo": 0.9, "bar": 0.6})
        preds = generate_predictions(schema)
        assert preds["foo"] == 0.9
        assert preds["bar"] == 0.6

    def test_prediction_errors_missing(self):
        preds = {"foo": 0.9, "bar": 0.6}
        errors = compute_prediction_error(preds, ["foo"])
        assert errors["bar"] > 0  # Missing prediction = positive error

    def test_prediction_errors_novel(self):
        preds = {"foo": 0.9}
        errors = compute_prediction_error(preds, ["foo", "novel"])
        assert errors["novel"] < 0  # Novel = negative error

    def test_free_energy_zero_for_perfect_match(self):
        preds = {"foo": 0.9}
        errors = compute_prediction_error(preds, ["foo"])
        fe = compute_schema_free_energy(errors)
        assert fe == 0.0  # No errors

    def test_free_energy_positive_for_mismatch(self):
        preds = {"foo": 0.9, "bar": 0.8}
        errors = compute_prediction_error(preds, [])  # Nothing observed
        fe = compute_schema_free_energy(errors)
        assert fe > 0


class TestSerialization:
    def test_roundtrip(self):
        schema = Schema(
            schema_id="s1",
            domain="test",
            label="test schema",
            entity_signature={"foo": 0.8},
            tag_signature={"tag": 0.5},
            relationship_types=[("file", "imports", "dependency")],
            formation_count=10,
            violation_count=2,
        )
        d = schema_to_dict(schema)
        restored = schema_from_dict(d)
        assert restored.schema_id == "s1"
        assert restored.entity_signature == {"foo": 0.8}
        assert restored.formation_count == 10
        assert len(restored.relationship_types) == 1
