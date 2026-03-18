"""Tests for mcp_server.core.dual_store_cls — CLS classification and clustering."""

from mcp_server.core.dual_store_cls import (
    classify_memory,
    auto_weight,
)
from mcp_server.core.dual_store_cls_abstraction import (
    cluster_by_similarity,
    filter_recurring_patterns,
    check_consistency,
    abstract_to_schema,
)


class TestClassifyMemory:
    def test_semantic_tag_overrides(self):
        assert classify_memory("anything", tags=["rule"]) == "semantic"
        assert classify_memory("anything", tags=["convention"]) == "semantic"
        assert classify_memory("anything", tags=["architecture"]) == "semantic"
        assert classify_memory("anything", tags=["principle"]) == "semantic"
        assert classify_memory("anything", tags=["best-practice"]) == "semantic"

    def test_specific_content_is_episodic(self):
        assert classify_memory("Error at line 42 in foo.py:42") == "episodic"
        assert classify_memory("Traceback on /Users/joe/project") == "episodic"
        assert classify_memory("Found at 0x7fff1234") == "episodic"
        assert classify_memory("Log from 2024-01-01T10:00") == "episodic"

    def test_decision_keywords_are_semantic(self):
        assert classify_memory("We should always use UTC") == "semantic"
        assert classify_memory("The convention is to use snake_case") == "semantic"
        assert classify_memory("Prefer composition over inheritance") == "semantic"

    def test_architecture_keywords_are_semantic(self):
        assert (
            classify_memory("The module follows hexagonal architecture") == "semantic"
        )
        assert classify_memory("This design pattern works well") == "semantic"

    def test_specificity_overrides_keywords(self):
        # Has both specific (line number) and semantic keywords (always)
        result = classify_memory("Always check line 42 in foo.py:42")
        assert result == "episodic"  # Specificity wins

    def test_generic_content_is_episodic(self):
        assert classify_memory("The weather is nice today") == "episodic"
        assert classify_memory("I wrote some code") == "episodic"

    def test_empty_content(self):
        assert classify_memory("") == "episodic"

    def test_case_insensitive_tags(self):
        assert classify_memory("content", tags=["Rule"]) == "semantic"
        assert classify_memory("content", tags=["ARCHITECTURE"]) == "semantic"


class TestClusterBySimilarity:
    def _sim(self, a, b):
        """Mock similarity: same embedding = 1.0, else 0.0."""
        return 1.0 if a == b else 0.0

    def test_identical_embeddings_cluster(self):
        mems = [
            {"id": 1, "embedding": b"A"},
            {"id": 2, "embedding": b"A"},
            {"id": 3, "embedding": b"B"},
        ]
        clusters = cluster_by_similarity(mems, self._sim, threshold=0.9)
        assert len(clusters) == 2
        assert len(clusters[0]) == 2  # A cluster
        assert len(clusters[1]) == 1  # B cluster

    def test_no_embeddings(self):
        mems = [{"id": 1}, {"id": 2}]
        clusters = cluster_by_similarity(mems, self._sim)
        assert len(clusters) == 2  # Each its own cluster

    def test_empty_input(self):
        assert cluster_by_similarity([], self._sim) == []

    def test_all_unique(self):
        mems = [{"id": i, "embedding": bytes([i])} for i in range(5)]
        clusters = cluster_by_similarity(mems, self._sim, threshold=0.9)
        assert len(clusters) == 5


class TestFilterRecurringPatterns:
    def test_filters_by_occurrences(self):
        cluster_small = [{"id": i} for i in range(2)]
        cluster_large = [{"id": i, "source": f"s{i}"} for i in range(5)]
        patterns = filter_recurring_patterns(
            [cluster_small, cluster_large], min_occurrences=3, min_sessions=1
        )
        assert len(patterns) == 1
        assert patterns[0]["count"] == 5

    def test_filters_by_sessions(self):
        # All same session
        cluster = [{"id": i, "source": "same"} for i in range(5)]
        patterns = filter_recurring_patterns(
            [cluster], min_occurrences=3, min_sessions=2
        )
        assert len(patterns) == 0

    def test_cross_session_passes(self):
        cluster = [
            {"id": 1, "source": "s1"},
            {"id": 2, "source": "s2"},
            {"id": 3, "source": "s1"},
        ]
        patterns = filter_recurring_patterns(
            [cluster], min_occurrences=3, min_sessions=2
        )
        assert len(patterns) == 1

    def test_empty_clusters(self):
        assert filter_recurring_patterns([], min_occurrences=3) == []


class TestCheckConsistency:
    def test_consistent_memories(self):
        mems = [
            {"content": "Always use UTC timestamps"},
            {"content": "UTC is the standard for all timestamps"},
        ]
        result = check_consistency(mems)
        assert result["consistent"] is True
        assert len(result["contradictions"]) == 0

    def test_contradictory_memories(self):
        mems = [
            {"content": "Always use UTC timestamps"},
            {"content": "We no longer use UTC, switched to local time"},
        ]
        result = check_consistency(mems)
        assert result["consistent"] is False
        assert len(result["contradictions"]) > 0

    def test_single_memory_consistent(self):
        result = check_consistency([{"content": "anything"}])
        assert result["consistent"] is True

    def test_empty_consistent(self):
        result = check_consistency([])
        assert result["consistent"] is True

    def test_negation_patterns(self):
        mems = [
            {"content": "Use the old API"},
            {"content": "The old API is deprecated, don't use it"},
        ]
        result = check_consistency(mems)
        assert result["consistent"] is False


class TestAbstractToSchema:
    def test_common_words_extracted(self):
        mems = [
            {"content": "Always use UTC timestamps in database"},
            {"content": "Always use UTC timestamps in API responses"},
            {"content": "Always use UTC timestamps in log files"},
        ]
        schema = abstract_to_schema(mems)
        assert "UTC" in schema or "utc" in schema.lower()
        assert "timestamps" in schema.lower()
        assert "3 observations" in schema

    def test_empty_memories(self):
        assert abstract_to_schema([]) == ""

    def test_common_tags_included(self):
        mems = [
            {"content": "Use UTC always", "tags": ["time", "convention"]},
            {"content": "Use UTC always", "tags": ["time"]},
            {"content": "Use UTC always", "tags": ["time", "other"]},
        ]
        schema = abstract_to_schema(mems)
        assert "time" in schema

    def test_stops_words_removed(self):
        mems = [
            {"content": "the quick brown fox"},
            {"content": "the quick brown dog"},
        ]
        schema = abstract_to_schema(mems)
        assert "the" not in schema.split(": ", 1)[-1].split()

    def test_caps_at_15_words(self):
        content = " ".join(f"word{i}" for i in range(30))
        mems = [{"content": content}] * 3
        schema = abstract_to_schema(mems)
        # Schema phrase should have at most 15 key words
        phrase = schema.split(": ", 1)[-1]
        words = phrase.strip().split()
        assert len(words) <= 15


class TestAutoWeight:
    def test_specific_query_prefers_episodic(self):
        ep, sem = auto_weight("error at line 42 in foo.py:42")
        assert ep > sem

    def test_semantic_query_prefers_semantic(self):
        ep, sem = auto_weight("what is our architecture principle?")
        assert sem > ep

    def test_generic_query_balanced(self):
        ep, sem = auto_weight("memory about the project")
        assert ep == sem
