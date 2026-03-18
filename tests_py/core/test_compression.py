"""Tests for mcp_server.core.compression — rate-distortion memory compression."""

from datetime import datetime, timezone, timedelta

from mcp_server.core.compression import (
    get_compression_schedule,
    extract_gist,
    generate_tag,
)


class TestGetCompressionSchedule:
    def test_recent_memory_level_zero(self):
        now = datetime.now(timezone.utc).isoformat()
        mem = {"created_at": now, "importance": 0.5, "store_type": "episodic"}
        assert get_compression_schedule(mem) == 0

    def test_medium_age_level_one(self):
        ten_days_ago = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        mem = {"created_at": ten_days_ago, "importance": 0.3, "store_type": "episodic"}
        assert get_compression_schedule(mem) == 1

    def test_old_memory_level_two(self):
        sixty_days_ago = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        mem = {
            "created_at": sixty_days_ago,
            "importance": 0.3,
            "store_type": "episodic",
        }
        assert get_compression_schedule(mem) == 2

    def test_protected_never_compressed(self):
        old = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        mem = {"created_at": old, "is_protected": True, "store_type": "episodic"}
        assert get_compression_schedule(mem) == 0

    def test_semantic_never_compressed(self):
        old = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        mem = {"created_at": old, "store_type": "semantic"}
        assert get_compression_schedule(mem) == 0

    def test_important_resists_compression(self):
        ten_days_ago = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        normal = {
            "created_at": ten_days_ago,
            "importance": 0.3,
            "store_type": "episodic",
        }
        important = {
            "created_at": ten_days_ago,
            "importance": 0.9,
            "store_type": "episodic",
        }
        # Important memory gets more resistance → stays at level 0 longer
        assert get_compression_schedule(important) <= get_compression_schedule(normal)

    def test_no_created_at(self):
        assert get_compression_schedule({}) == 0

    def test_invalid_timestamp(self):
        assert get_compression_schedule({"created_at": "invalid"}) == 0


class TestExtractGist:
    def test_short_content_preserved(self):
        content = "One sentence. Two sentence. Three."
        gist = extract_gist(content)
        assert "One sentence" in gist
        assert "Three" in gist

    def test_long_content_compressed(self):
        sentences = [f"Sentence {i} about topic {i}." for i in range(20)]
        content = " ".join(sentences)
        gist = extract_gist(content)
        # Gist should be shorter than original
        assert len(gist) < len(content)
        # First and last sentences preserved (primacy-recency)
        assert "Sentence 0" in gist
        assert "Sentence 19" in gist

    def test_code_blocks_preserved(self):
        content = (
            "Some text.\n```python\ndef foo():\n    pass\n```\nMore text about things."
        )
        gist = extract_gist(content)
        assert "```python" in gist
        assert "def foo():" in gist

    def test_error_sentences_prioritized(self):
        # Need enough sentences so the algorithm has to select
        lines = [
            "Introduction to the module.",
            "This is normal filler text number one.",
            "Another filler line that says nothing useful.",
            "Yet more filler content padding.",
            "RuntimeError occurred in the parser.",
            "More filler content here that is boring.",
            "Additional padding sentence number six.",
            "Even more filler to make it longer.",
            "The conclusion of this section.",
        ]
        content = "\n".join(lines)
        gist = extract_gist(content)
        assert "RuntimeError" in gist

    def test_empty_content(self):
        assert extract_gist("") == ""

    def test_decision_sentences_prioritized(self):
        sentences = [
            "General intro.",
            "Some filler.",
            "We decided to use PostgreSQL for the database.",
            "More filler.",
            "End.",
        ]
        gist = extract_gist("\n".join(sentences))
        assert "PostgreSQL" in gist


class TestGenerateTag:
    def test_basic_tag(self):
        memory = {
            "tags": ["python", "core"],
            "created_at": "2024-06-15T10:00:00Z",
        }
        tag = generate_tag("The EmbeddingEngine handles vector encoding", memory)
        assert "EmbeddingEngine" in tag
        assert "2024-06-15" in tag
        assert len(tag) <= 200

    def test_long_content_truncated(self):
        memory = {"tags": [], "created_at": "2024-01-01T00:00:00Z"}
        long_content = "A" * 300
        tag = generate_tag(long_content, memory)
        assert len(tag) <= 200

    def test_includes_camelcase_entities(self):
        memory = {"tags": [], "created_at": "2024-01-01T00:00:00Z"}
        tag = generate_tag("The MemoryStore and EmbeddingEngine work together", memory)
        assert "MemoryStore" in tag or "EmbeddingEngine" in tag

    def test_includes_memory_tags(self):
        memory = {
            "tags": ["architecture", "refactor"],
            "created_at": "2024-01-01T00:00:00Z",
        }
        tag = generate_tag("Some content", memory)
        assert "architecture" in tag or "refactor" in tag

    def test_unknown_date(self):
        memory = {"tags": [], "created_at": ""}
        tag = generate_tag("Content", memory)
        assert "unknown" in tag
