"""Tests for mcp_server.core.metacognition — coverage, gaps, cognitive load."""

from datetime import timedelta

from mcp_server.core.metacognition import (
    detect_isolated_entities,
    detect_stale_regions,
    detect_low_confidence,
    detect_missing_connections,
    detect_unresolved_errors,
    detect_all_gaps,
)
from mcp_server.core.metacognition_analysis import (
    compute_coverage,
    chunk_memories,
    manage_context,
    summarize_overflow,
    DEFAULT_MAX_CHUNKS,
)


class TestComputeCoverage:
    def test_high_coverage(self):
        result = compute_coverage(
            matching_count=10,
            entity_coverage=0.9,
            newest_age=timedelta(hours=1),
            avg_confidence=0.9,
        )
        assert result["coverage"] >= 0.7
        assert result["suggestion"] == "sufficient"

    def test_low_coverage(self):
        result = compute_coverage(
            matching_count=0,
            entity_coverage=0.0,
            newest_age=None,
            avg_confidence=0.0,
        )
        assert result["coverage"] < 0.4
        assert result["suggestion"] == "insufficient"

    def test_partial_coverage(self):
        result = compute_coverage(
            matching_count=2,
            entity_coverage=0.5,
            newest_age=timedelta(days=5),
            avg_confidence=0.6,
        )
        assert 0.4 <= result["coverage"] < 0.7
        assert result["suggestion"] == "partial"

    def test_density_thresholds(self):
        # 0 matches
        r0 = compute_coverage(0, 0.0, None, 0.0)
        assert r0["density"] == 0.0

        # 1-2 matches
        r1 = compute_coverage(1, 0.0, None, 0.0)
        assert r1["density"] == 0.3

        # 3-5 matches
        r3 = compute_coverage(4, 0.0, None, 0.0)
        assert r3["density"] == 0.6

        # 6+ matches
        r6 = compute_coverage(10, 0.0, None, 0.0)
        assert r6["density"] == 0.9

    def test_recency_thresholds(self):
        r_recent = compute_coverage(1, 0.0, timedelta(hours=12), 0.0)
        assert r_recent["recency"] == 1.0

        r_week = compute_coverage(1, 0.0, timedelta(days=3), 0.0)
        assert r_week["recency"] == 0.7

        r_month = compute_coverage(1, 0.0, timedelta(days=15), 0.0)
        assert r_month["recency"] == 0.4

        r_old = compute_coverage(1, 0.0, timedelta(days=60), 0.0)
        assert r_old["recency"] == 0.2

    def test_no_matches_zero_recency(self):
        result = compute_coverage(0, 0.0, None, 0.0)
        assert result["recency"] == 0.0


class TestDetectIsolatedEntities:
    def test_isolated_entities(self):
        entities = [
            {"id": 1, "name": "foo"},
            {"id": 2, "name": "bar"},
        ]
        rel_counts = {1: 0, 2: 5}
        gaps = detect_isolated_entities(entities, rel_counts)
        assert len(gaps) == 1
        assert gaps[0]["entities"] == ["foo"]
        assert gaps[0]["severity"] == 0.6

    def test_single_connection(self):
        entities = [{"id": 1, "name": "weak"}]
        rel_counts = {1: 1}
        gaps = detect_isolated_entities(entities, rel_counts)
        assert len(gaps) == 1
        assert gaps[0]["severity"] == 0.4

    def test_well_connected(self):
        entities = [{"id": 1, "name": "strong"}]
        rel_counts = {1: 5}
        gaps = detect_isolated_entities(entities, rel_counts)
        assert len(gaps) == 0


class TestDetectStaleRegions:
    def test_stale_region(self):
        mems = [
            {"heat": 0.1, "domain": "backend"},
            {"heat": 0.2, "domain": "backend"},
            {"heat": 0.9, "domain": "frontend"},
        ]
        gaps = detect_stale_regions(mems, heat_threshold=0.3)
        assert len(gaps) == 1
        assert "backend" in gaps[0]["description"]

    def test_no_stale(self):
        mems = [{"heat": 0.9, "domain": "a"}, {"heat": 0.8, "domain": "a"}]
        gaps = detect_stale_regions(mems, heat_threshold=0.3)
        assert len(gaps) == 0

    def test_min_stale_threshold(self):
        mems = [{"heat": 0.1, "domain": "a"}]
        gaps = detect_stale_regions(mems, min_stale=2)
        assert len(gaps) == 0  # Only 1 stale, need 2


class TestDetectLowConfidence:
    def test_low_confidence_found(self):
        mems = [
            {"confidence": 0.3},
            {"confidence": 0.4},
            {"confidence": 0.9},
        ]
        gaps = detect_low_confidence(mems, confidence_threshold=0.5)
        assert len(gaps) == 1
        assert "2 memories" in gaps[0]["description"]

    def test_all_high_confidence(self):
        mems = [{"confidence": 0.9}, {"confidence": 0.8}]
        gaps = detect_low_confidence(mems, confidence_threshold=0.5)
        assert len(gaps) == 0


class TestDetectMissingConnections:
    def test_missing_found(self):
        co_occurring = [("A", "B"), ("C", "D")]
        existing = {("A", "B")}
        gaps = detect_missing_connections(co_occurring, existing)
        assert len(gaps) == 1
        assert "C" in gaps[0]["entities"] or "D" in gaps[0]["entities"]

    def test_reverse_direction_counts(self):
        co_occurring = [("A", "B")]
        existing = {("B", "A")}  # Reverse
        gaps = detect_missing_connections(co_occurring, existing)
        assert len(gaps) == 0

    def test_all_connected(self):
        co_occurring = [("A", "B")]
        existing = {("A", "B")}
        gaps = detect_missing_connections(co_occurring, existing)
        assert len(gaps) == 0


class TestDetectUnresolvedErrors:
    def test_unresolved_found(self):
        errors = [{"id": 1, "name": "TypeError"}, {"id": 2, "name": "ValueError"}]
        resolved = {1}
        gaps = detect_unresolved_errors(errors, resolved)
        assert len(gaps) == 1
        assert "ValueError" in gaps[0]["entities"]

    def test_all_resolved(self):
        errors = [{"id": 1, "name": "TypeError"}]
        resolved = {1}
        gaps = detect_unresolved_errors(errors, resolved)
        assert len(gaps) == 0


class TestDetectAllGaps:
    def test_combined_detection(self):
        gaps = detect_all_gaps(
            entities=[{"id": 1, "name": "orphan"}],
            relationship_counts={},
            memories=[{"heat": 0.1, "domain": "a"}, {"heat": 0.05, "domain": "a"}],
            co_occurring_pairs=[],
            existing_relationships=set(),
            error_entities=[],
            resolved_entity_ids=set(),
        )
        assert len(gaps) >= 1  # At least isolated entity + stale region

    def test_sorted_by_severity(self):
        gaps = detect_all_gaps(
            entities=[{"id": 1, "name": "a"}],
            relationship_counts={},
            memories=[
                {"heat": 0.1, "domain": "x", "confidence": 0.3},
                {"heat": 0.1, "domain": "x", "confidence": 0.4},
            ],
            co_occurring_pairs=[("X", "Y")],
            existing_relationships=set(),
            error_entities=[{"id": 10, "name": "Err"}],
            resolved_entity_ids=set(),
        )
        if len(gaps) >= 2:
            assert gaps[0]["severity"] >= gaps[1]["severity"]


class TestChunkMemories:
    def test_entity_overlap_clusters(self):
        mems = [
            {"id": 1, "tags": ["python", "testing"]},
            {"id": 2, "tags": ["python", "testing", "pytest"]},
            {"id": 3, "tags": ["javascript", "react"]},
        ]
        chunks = chunk_memories(mems, entity_overlap_threshold=0.3)
        assert len(chunks) == 2  # python pair + javascript

    def test_temporal_proximity_clusters(self):
        mems = [
            {"id": 1, "tags": ["a"], "created_at": "2024-01-01T10:00:00Z"},
            {"id": 2, "tags": ["b"], "created_at": "2024-01-01T10:30:00Z"},
            {"id": 3, "tags": ["c"], "created_at": "2024-06-01T10:00:00Z"},
        ]
        chunks = chunk_memories(mems, temporal_window_hours=2.0)
        assert len(chunks) == 2

    def test_empty_input(self):
        assert chunk_memories([]) == []

    def test_single_memory(self):
        chunks = chunk_memories([{"id": 1, "tags": []}])
        assert len(chunks) == 1


class TestManageContext:
    def test_within_limit(self):
        mems = [{"id": i, "tags": []} for i in range(3)]
        result = manage_context(mems, max_chunks=5)
        assert all(m["_position_reason"] == "within_limit" for m in result)

    def test_primacy_recency_applied(self):
        mems = [
            {
                "id": i,
                "tags": [f"t{i}"],
                "importance": 0.1 * i,
                "heat": 0.5,
                "confidence": 0.5,
            }
            for i in range(10)
        ]
        result = manage_context(mems, max_chunks=3)
        reasons = [m["_position_reason"] for m in result]
        assert "primacy" in reasons
        assert "recency" in reasons

    def test_default_max_chunks(self):
        assert DEFAULT_MAX_CHUNKS == 5

    def test_overflow_marked(self):
        mems = [
            {
                "id": i,
                "tags": [f"unique{i}"],
                "importance": 0.1,
                "heat": 0.5,
                "confidence": 0.5,
            }
            for i in range(20)
        ]
        result = manage_context(mems, max_chunks=3)
        reasons = {m["_position_reason"] for m in result}
        assert "overflow" in reasons


class TestSummarizeOverflow:
    def test_preserves_high_surprise(self):
        mems = [
            {"content": "important discovery", "surprise": 0.9, "importance": 0.1},
            {"content": "boring fact", "surprise": 0.1, "importance": 0.1},
        ]
        result = summarize_overflow(mems)
        preserved = [m for m in result if m["content"] == "important discovery"]
        assert len(preserved) == 1

    def test_preserves_high_importance(self):
        mems = [
            {"content": "critical rule", "surprise": 0.1, "importance": 0.9},
            {"content": "trivial note", "surprise": 0.1, "importance": 0.1},
        ]
        result = summarize_overflow(mems)
        preserved = [m for m in result if m["content"] == "critical rule"]
        assert len(preserved) == 1

    def test_summary_created(self):
        mems = [
            {"content": f"note {i}", "surprise": 0.1, "importance": 0.1, "heat": 0.3}
            for i in range(5)
        ]
        result = summarize_overflow(mems)
        summaries = [m for m in result if "Summary of" in m.get("content", "")]
        assert len(summaries) == 1

    def test_empty_input(self):
        result = summarize_overflow([])
        assert result == []
