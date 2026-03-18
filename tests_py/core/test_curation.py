"""Tests for mcp_server.core.curation — active memory curation."""

from mcp_server.core.curation import (
    decide_curation_action,
    compute_textual_overlap,
    merge_contents,
    merge_tags,
    detect_contradictions,
    identify_prunable,
    identify_strengtheneable,
    compute_relationship_reweights,
    identify_derivable_facts,
)


class TestDecideCurationAction:
    def test_merge_on_high_similarity_with_overlap(self):
        assert decide_curation_action(0.9, True) == "merge"

    def test_link_on_medium_similarity(self):
        assert decide_curation_action(0.7, False) == "link"

    def test_create_on_low_similarity(self):
        assert decide_curation_action(0.3, False) == "create"

    def test_high_similarity_without_overlap_links(self):
        assert decide_curation_action(0.9, False) == "link"

    def test_boundary_merge_threshold(self):
        assert decide_curation_action(0.85, True) == "merge"
        assert (
            decide_curation_action(0.84, False) == "link"
        )  # Above link_low, no overlap

    def test_boundary_link_threshold(self):
        assert decide_curation_action(0.6, False) == "link"
        assert decide_curation_action(0.59, False) == "create"


class TestComputeTextualOverlap:
    def test_identical_texts(self):
        assert compute_textual_overlap("hello world", "hello world") == 1.0

    def test_no_overlap(self):
        assert compute_textual_overlap("foo bar", "baz qux") == 0.0

    def test_partial_overlap(self):
        result = compute_textual_overlap("use UTC timestamps", "always use UTC")
        assert 0.0 < result < 1.0

    def test_empty_text(self):
        assert compute_textual_overlap("", "hello") == 0.0
        assert compute_textual_overlap("hello", "") == 0.0


class TestMergeContents:
    def test_new_content_appended(self):
        result = merge_contents("fact A", "fact B")
        assert "fact A" in result
        assert "fact B" in result

    def test_duplicate_content_not_appended(self):
        result = merge_contents("fact A is true", "fact A is true")
        assert result.count("fact A") == 1

    def test_subset_content_uses_larger(self):
        result = merge_contents("fact A", "fact A with more detail")
        assert result == "fact A with more detail"


class TestMergeTags:
    def test_union_of_tags(self):
        assert merge_tags(["a", "b"], ["b", "c"]) == ["a", "b", "c"]

    def test_preserves_order(self):
        result = merge_tags(["x", "y"], ["z"])
        assert result == ["x", "y", "z"]

    def test_empty_lists(self):
        assert merge_tags([], []) == []


class TestDetectContradictions:
    def test_negation_mismatch(self):
        similar = [{"id": 1, "content": "We don't use PostgreSQL anymore"}]
        result = detect_contradictions("Use PostgreSQL for all databases", similar)
        assert len(result) == 1
        assert result[0]["type"] == "negation_mismatch"
        assert result[0]["confidence_penalty"] == 0.2

    def test_action_divergence(self):
        similar = [{"id": 1, "content": "We deploy with Docker containers"}]
        result = detect_contradictions("We build via Kubernetes", similar)
        assert len(result) == 1
        assert result[0]["type"] == "action_divergence"

    def test_no_contradiction(self):
        similar = [{"id": 1, "content": "Use UTC timestamps in the database"}]
        result = detect_contradictions("Use UTC timestamps in API responses", similar)
        assert len(result) == 0

    def test_empty_similar(self):
        assert detect_contradictions("anything", []) == []


class TestIdentifyPrunable:
    def test_cold_low_confidence_unused(self):
        mems = [
            {"id": 1, "heat": 0.005, "confidence": 0.1, "access_count": 0},
            {"id": 2, "heat": 0.5, "confidence": 0.9, "access_count": 5},
        ]
        assert identify_prunable(mems) == [1]

    def test_accessed_not_pruned(self):
        mems = [{"id": 1, "heat": 0.005, "confidence": 0.1, "access_count": 1}]
        assert identify_prunable(mems) == []

    def test_empty(self):
        assert identify_prunable([]) == []


class TestIdentifyStrengtheneable:
    def test_high_access_high_confidence(self):
        mems = [
            {"id": 1, "access_count": 10, "confidence": 0.9, "importance": 0.5},
            {"id": 2, "access_count": 1, "confidence": 0.9, "importance": 0.5},
        ]
        result = identify_strengtheneable(mems)
        assert len(result) == 1
        assert result[0][0] == 1
        assert result[0][1] == 0.6

    def test_already_max_importance(self):
        mems = [{"id": 1, "access_count": 10, "confidence": 0.9, "importance": 1.0}]
        result = identify_strengtheneable(mems)
        assert len(result) == 0  # Can't boost past 1.0

    def test_empty(self):
        assert identify_strengtheneable([]) == []


class TestComputeRelationshipReweights:
    def test_hot_entities_boosted(self):
        rels = [
            {"id": 1, "source_entity_id": 10, "target_entity_id": 20, "weight": 1.0}
        ]
        heats = {10: 0.9, 20: 0.8}
        result = compute_relationship_reweights(rels, heats)
        assert len(result) == 1
        assert result[0][1] > 1.0  # Boosted

    def test_cold_entities_decayed(self):
        rels = [
            {"id": 1, "source_entity_id": 10, "target_entity_id": 20, "weight": 2.0}
        ]
        heats = {10: 0.05, 20: 0.05}
        result = compute_relationship_reweights(rels, heats)
        assert len(result) == 1
        assert result[0][1] < 2.0  # Decayed

    def test_medium_heat_no_change(self):
        rels = [
            {"id": 1, "source_entity_id": 10, "target_entity_id": 20, "weight": 1.0}
        ]
        heats = {10: 0.4, 20: 0.4}
        result = compute_relationship_reweights(rels, heats)
        assert len(result) == 0  # No change


class TestIdentifyDerivableFacts:
    def test_high_weight_generates_fact(self):
        rels = [
            {
                "source_entity_id": 1,
                "target_entity_id": 2,
                "relationship_type": "co_occurrence",
                "weight": 15.0,
            },
        ]
        names = {1: "foo.py", 2: "bar.py"}
        facts = identify_derivable_facts(rels, names)
        assert len(facts) == 1
        assert "foo.py" in facts[0]
        assert "bar.py" in facts[0]

    def test_low_weight_no_fact(self):
        rels = [
            {
                "source_entity_id": 1,
                "target_entity_id": 2,
                "relationship_type": "co_occurrence",
                "weight": 2.0,
            }
        ]
        facts = identify_derivable_facts(rels, {1: "a", 2: "b"})
        assert len(facts) == 0
