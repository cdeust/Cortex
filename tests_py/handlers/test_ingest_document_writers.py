"""Unit tests for ingest_document_writers — fake store, no live DB (issue #192)."""

from __future__ import annotations

from mcp_server.core.document_model import (
    DocumentProvenance,
)
from mcp_server.core.document_normalizer import NormalizedDocument, SectionMemory
from mcp_server.handlers.ingest_document_writers import (
    DocumentMemoryContext,
    content_version,
    write_document_memories,
)

_PROV = DocumentProvenance(source="/d.docx", version="v1", source_kind="docx")


class _FakeStore:
    def __init__(self, existing_by_tag=None, fail_inserts=False):
        self.memories: list[dict] = []
        self._next = 100
        self._existing_by_tag = existing_by_tag or {}
        self._fail = fail_inserts

    def insert_memory(self, data: dict) -> int:
        if self._fail:
            raise RuntimeError("db down")
        mid = self._next
        self._next += 1
        self.memories.append({**data, "id": mid})
        return mid

    def get_memories_by_tag(
        self, tag: str, limit: int = 20, heads_only: bool = True
    ) -> list[dict]:
        self.last_tag_query = (tag, limit)
        return self._existing_by_tag.get(tag, [])


def _normalized() -> NormalizedDocument:
    return NormalizedDocument(
        wiki_rel_path="documents/d.md",
        wiki_markdown="# D\n",
        summary="Document ingested: 'D'.",
        section_memories=[SectionMemory("Intro", "[Intro]\n\nbody")],
        notices=[],
        image_count=0,
    )


class TestContentVersion:
    def test_deterministic_and_sensitive_to_content(self):
        assert content_version("abc") == content_version("abc")
        assert content_version("abc") != content_version("abd")

    def test_is_16_hex_chars(self):
        v = content_version("anything")
        assert len(v) == 16 and all(c in "0123456789abcdef" for c in v)


class TestWriteDocumentMemories:
    def test_summary_record_is_exact(self):
        store = _FakeStore()
        out = write_document_memories(
            DocumentMemoryContext(store, _PROV, "dom", "/dir"), _normalized()
        )
        summary = {k: v for k, v in store.memories[0].items() if k != "id"}
        assert summary == {
            "content": "Document ingested: 'D'.",
            "tags": [
                "document",
                "ingest",
                "docx",
                "doc-ingest:docx:/d.docx@v1",
                "doc-src:docx:/d.docx",
                "summary",
            ],
            "source": "ingest_document:/d.docx",
            "domain": "dom",
            "directory_context": "/dir",
            "importance": 0.8,
            "heat": 0.9,
            "confidence": 0.9,
            "is_protected": True,
            "write_class": "mechanical",
        }
        assert out["summary_memory_id"] == store.memories[0]["id"]

    def test_section_record_is_exact(self):
        store = _FakeStore()
        out = write_document_memories(
            DocumentMemoryContext(store, _PROV, "dom", "/dir"), _normalized()
        )
        section = {k: v for k, v in store.memories[1].items() if k != "id"}
        assert section == {
            "content": "[Intro]\n\nbody",
            "tags": [
                "document",
                "ingest",
                "docx",
                "doc-ingest:docx:/d.docx@v1",
                "doc-src:docx:/d.docx",
                "section",
            ],
            "source": "ingest_document:/d.docx",
            "domain": "dom",
            "directory_context": "/dir",
            "importance": 0.5,
            "heat": 0.6,
            "confidence": 0.9,
            "is_protected": False,
            "write_class": "mechanical",
        }
        assert out["section_memory_ids"] == [store.memories[1]["id"]]

    def test_summary_and_section_have_distinct_importance_heat(self):
        # Guards against the summary/section field values being swapped.
        store = _FakeStore()
        write_document_memories(
            DocumentMemoryContext(store, _PROV, "dom", "/dir"), _normalized()
        )
        assert store.memories[0]["importance"] == 0.8
        assert store.memories[1]["importance"] == 0.5
        assert store.memories[0]["is_protected"] is True
        assert store.memories[1]["is_protected"] is False

    def test_insert_failure_survived_and_logged_with_exact_messages(self, caplog):
        store = _FakeStore(fail_inserts=True)
        out = write_document_memories(
            DocumentMemoryContext(store, _PROV, "dom", "/dir"), _normalized()
        )
        assert out["summary_memory_id"] is None
        assert out["section_memory_ids"] == []
        assert out["failures"] == {"summary": "db down", "section:0": "db down"}
        assert out["completed_components"] == []
        # Exact formatted messages — the failing exception text AND the section
        # heading must reach the log (guards the log-arg wiring).
        msgs = [r.getMessage() for r in caplog.records]
        assert "ingest_document summary insert failed: db down" in msgs
        assert "ingest_document section:0 insert failed: db down" in msgs


def test_section_only_receipt_does_not_skip_summary():
    from tests_py.handlers.test_ingest_document import _FakeStore as Store

    store = Store()
    tag = "doc-ingest:docx:/d.docx@v1"
    section_id = store.insert_memory(
        {"content": "[Intro]\n\nbody", "tags": [tag, "section"]}
    )
    result = write_document_memories(
        DocumentMemoryContext(store, _PROV, "dom", "/dir"), _normalized()
    )
    assert result["summary_memory_id"] != section_id
    assert result["section_memory_ids"] == [section_id]
    assert result["completed_components"] == ["summary", "section:0"]
    assert len(store.memories) == 2


def test_missing_id_returned_by_store_is_failure():
    class Store(_FakeStore):
        def insert_memory(self, record):
            return None

    result = write_document_memories(
        DocumentMemoryContext(Store(), _PROV, "dom", "/dir"), _normalized()
    )
    assert result["completed_components"] == []
    assert result["failures"] == {
        "summary": "insert returned no memory id",
        "section:0": "insert returned no memory id",
    }


def test_receipt_scan_rechecks_tags_roles_content_and_ids():
    tag = "doc-ingest:docx:/d.docx@v1"
    invalid_rows = [
        {"id": 7, "tags": ["unrelated"], "content": "Document ingested: 'D'."},
        {"id": None, "tags": [tag, "summary"], "content": "Document ingested: 'D'."},
        {"id": 7, "tags": [tag, "section"], "content": "different section"},
    ]
    for invalid in invalid_rows:
        store = _FakeStore(existing_by_tag={tag: [invalid]})
        result = write_document_memories(
            DocumentMemoryContext(store, _PROV, "dom", "/dir"), _normalized()
        )
        assert len(store.memories) == 2
        assert result["completed_components"] == ["summary", "section:0"]
        assert result["failures"] == {}
        assert store.last_tag_query == (tag, 3)
