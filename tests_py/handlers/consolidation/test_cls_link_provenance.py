"""Tests for CLS source-memory provenance (fix/memory-link-fk-violation).

source: ADR-0938"""

from __future__ import annotations

from mcp_server.handlers.consolidation.cls import (
    _create_semantic_memories,
    _with_source_provenance,
)


class TestWithSourceProvenance:
    def test_appends_one_marker_per_source_id(self):
        tags = _with_source_provenance(["existing"], [11, 22, 33])
        assert "existing" in tags
        assert "cls-derived" in tags
        assert "derived-src:11" in tags
        assert "derived-src:22" in tags
        assert "derived-src:33" in tags

    def test_filters_none_source_ids(self):
        tags = _with_source_provenance([], [5, None, 6])
        assert "derived-src:5" in tags
        assert "derived-src:6" in tags
        assert not any(t.endswith(":None") for t in tags)

    def test_empty_sources_still_tags_category(self):
        tags = _with_source_provenance(["x"], [])
        assert tags == ["x", "cls-derived"]

    def test_does_not_mutate_input_list(self):
        original = ["keep"]
        _with_source_provenance(original, [1])
        assert original == ["keep"]


class _FakeEmbeddings:
    def encode(self, _text: str):
        return [0.1, 0.2]


class _FakeStore:
    def __init__(self):
        self.inserted: list[dict] = []
        self.relationship_calls: list[dict] = []

    def insert_memory(self, record: dict) -> int:
        self.inserted.append(record)
        return len(self.inserted)

    def insert_relationship(self, data: dict) -> int:
        # Must never be called by the fixed code path -- the FK-violating
        # call site was removed, not silenced.
        self.relationship_calls.append(data)
        raise AssertionError(
            "insert_relationship must not be called for source-memory "
            "provenance after the fix (tags carry provenance instead)"
        )


class TestCreateSemanticMemoriesWritesProvenanceTags:
    def test_new_row_carries_source_tags_no_relationship_insert(self):
        store = _FakeStore()
        plan = {
            "new_semantics": [
                {
                    "schema": "users prefer dark mode",
                    "source_memory_ids": [101, 102, 103],
                    "tags": ["ui"],
                    "confabulation_risk": False,
                }
            ]
        }
        created = _create_semantic_memories(store, _FakeEmbeddings(), plan)

        assert created == 1
        assert len(store.inserted) == 1
        row_tags = store.inserted[0]["tags"]
        assert "cls-derived" in row_tags
        assert "derived-src:101" in row_tags
        assert "derived-src:102" in row_tags
        assert "derived-src:103" in row_tags
        # Root-cause verification: the FK-violating relationship path is gone.
        assert store.relationship_calls == []
