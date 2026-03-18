"""Tests for mcp_server.core.narrative — project story generation."""

from mcp_server.core.narrative import (
    extract_decisions,
    extract_events,
    extract_top_entities,
    extract_hot_topics,
    generate_narrative,
    generate_brief_summary,
)


class TestExtractDecisions:
    def test_keyword_match(self):
        mems = [
            {"content": "We decided to use PostgreSQL for all databases", "tags": []},
            {"content": "The weather is nice", "tags": []},
        ]
        decisions = extract_decisions(mems)
        assert len(decisions) == 1
        assert "PostgreSQL" in decisions[0]

    def test_tag_match(self):
        mems = [{"content": "Use UTC timestamps", "tags": ["decision"]}]
        decisions = extract_decisions(mems)
        assert len(decisions) == 1

    def test_no_decisions(self):
        mems = [{"content": "Just a normal note", "tags": []}]
        assert extract_decisions(mems) == []

    def test_truncation(self):
        long_content = "We decided to " + "x" * 200
        mems = [{"content": long_content, "tags": []}]
        decisions = extract_decisions(mems)
        assert len(decisions[0]) <= 155  # 150 + "..."

    def test_string_tags(self):
        mems = [{"content": "Important choice", "tags": "decision,important"}]
        decisions = extract_decisions(mems)
        assert len(decisions) == 1

    def test_multiple_keywords(self):
        mems = [
            {"content": "We chose React", "tags": []},
            {"content": "We switched to TypeScript", "tags": []},
            {"content": "We migrated to AWS", "tags": []},
        ]
        assert len(extract_decisions(mems)) == 3


class TestExtractEvents:
    def test_keyword_match(self):
        mems = [
            {"content": "Fixed the authentication bug", "importance": 0.3, "tags": []},
        ]
        events = extract_events(mems)
        assert len(events) == 1

    def test_high_importance(self):
        mems = [
            {"content": "Major architecture change", "importance": 0.9},
        ]
        events = extract_events(mems, importance_threshold=0.7)
        assert len(events) == 1

    def test_low_importance_no_keywords(self):
        mems = [{"content": "Made a small change", "importance": 0.2}]
        events = extract_events(mems)
        assert len(events) == 0


class TestExtractTopEntities:
    def test_camel_case_entities(self):
        mems = [
            {"content": "Updated MemoryStore and EmbeddingEngine classes"},
            {"content": "MemoryStore handles persistence"},
        ]
        entities = extract_top_entities(mems)
        assert "MemoryStore" in entities

    def test_file_paths(self):
        mems = [{"content": "Modified src/store.py and src/handler.py"}]
        entities = extract_top_entities(mems)
        assert any("store.py" in e for e in entities)

    def test_max_entities(self):
        mems = [{"content": " ".join(f"Entity{i}" for i in range(20))}]
        entities = extract_top_entities(mems, max_entities=5)
        assert len(entities) <= 5


class TestExtractHotTopics:
    def test_hot_memories_extracted(self):
        mems = [
            {"content": "Working on database optimization", "heat": 0.9},
            {"content": "Old note about setup", "heat": 0.1},
        ]
        topics = extract_hot_topics(mems, heat_threshold=0.7)
        assert len(topics) == 1
        assert "database" in topics[0]

    def test_sorted_by_heat(self):
        mems = [
            {"content": "Medium priority", "heat": 0.75},
            {"content": "Top priority", "heat": 0.95},
        ]
        topics = extract_hot_topics(mems, heat_threshold=0.7)
        assert "Top" in topics[0]

    def test_max_topics(self):
        mems = [{"content": f"Topic {i}", "heat": 0.9} for i in range(10)]
        topics = extract_hot_topics(mems, max_topics=3)
        assert len(topics) == 3


class TestGenerateNarrative:
    def test_full_narrative(self):
        mems = [
            {
                "content": "We decided to use SQLite for storage",
                "tags": ["decision"],
                "importance": 0.8,
                "heat": 0.9,
            },
            {
                "content": "Fixed the connection timeout bug",
                "tags": [],
                "importance": 0.6,
                "heat": 0.7,
            },
            {
                "content": "Updated MemoryStore class",
                "tags": [],
                "importance": 0.3,
                "heat": 0.3,
            },
        ]
        result = generate_narrative(mems, directory="/project")
        assert "Key Decisions" in result["narrative"]
        assert "Significant Events" in result["narrative"]
        assert result["memory_count"] == 3
        assert len(result["decisions"]) >= 1
        assert len(result["events"]) >= 1

    def test_empty_memories(self):
        result = generate_narrative([])
        assert "No significant activity" in result["narrative"]
        assert result["memory_count"] == 0

    def test_with_period_label(self):
        result = generate_narrative(
            [{"content": "test", "tags": [], "importance": 0.5, "heat": 0.5}],
            period_label="last 24h",
        )
        assert "last 24h" in result["narrative"]


class TestGenerateBriefSummary:
    def test_brief_with_content(self):
        mems = [
            {
                "content": "Working on API redesign",
                "heat": 0.9,
                "tags": ["decision"],
                "importance": 0.7,
            },
        ]
        summary = generate_brief_summary(mems)
        assert len(summary) > 0
        assert len(summary) <= 300

    def test_brief_empty(self):
        summary = generate_brief_summary([])
        assert summary == ""

    def test_truncation(self):
        mems = [
            {
                "content": "x" * 200,
                "heat": 0.9,
                "importance": 0.9,
                "tags": ["decision"],
            },
        ] * 10
        summary = generate_brief_summary(mems, max_chars=100)
        assert len(summary) <= 100
