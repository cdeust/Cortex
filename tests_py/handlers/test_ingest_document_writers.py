"""Unit tests for ingest_document_writers — fake store, no live DB (issue #192)."""

from __future__ import annotations

from mcp_server.core.document_model import DocumentProvenance
from mcp_server.core.document_normalizer import NormalizedDocument, SectionMemory
from mcp_server.handlers.ingest_document_writers import (
    already_ingested,
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

    def get_memories_by_tag(self, tag: str, limit: int = 20) -> list[dict]:
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


class TestAlreadyIngested:
    def test_none_when_never_ingested(self):
        assert already_ingested(_FakeStore(), _PROV) is None

    def test_returns_id_when_version_tag_present(self):
        tag = _PROV.dedup_tag()
        store = _FakeStore(existing_by_tag={tag: [{"id": 7, "tags": [tag]}]})
        assert already_ingested(store, _PROV) == 7

    def test_new_version_is_not_a_hit(self):
        old = DocumentProvenance("/d.docx", "v0", "docx")
        store = _FakeStore(
            existing_by_tag={old.dedup_tag(): [{"id": 7, "tags": [old.dedup_tag()]}]}
        )
        assert already_ingested(store, _PROV) is None

    def test_degrades_when_store_lacks_tag_query(self):
        class _NoTag:
            pass

        assert already_ingested(_NoTag(), _PROV) is None

    def test_queries_the_dedup_tag_with_bounded_limit(self):
        store = _FakeStore()
        already_ingested(store, _PROV)
        assert store.last_tag_query == (_PROV.dedup_tag(), 5)

    def test_ignores_rows_that_lack_the_dedup_tag(self):
        # A tag-query hit whose row does not actually carry the dedup tag is
        # not a match (guards the in-row tag re-check).
        tag = _PROV.dedup_tag()
        store = _FakeStore(existing_by_tag={tag: [{"id": 9, "tags": ["unrelated"]}]})
        assert already_ingested(store, _PROV) is None


class TestWriteDocumentMemories:
    def test_summary_record_is_exact(self):
        store = _FakeStore()
        out = write_document_memories(store, _normalized(), _PROV, "dom", "/dir")
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
        out = write_document_memories(store, _normalized(), _PROV, "dom", "/dir")
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
        write_document_memories(store, _normalized(), _PROV, "dom", "/dir")
        assert store.memories[0]["importance"] == 0.8
        assert store.memories[1]["importance"] == 0.5
        assert store.memories[0]["is_protected"] is True
        assert store.memories[1]["is_protected"] is False

    def test_insert_failure_survived_and_logged_with_exact_messages(self, caplog):
        store = _FakeStore(fail_inserts=True)
        out = write_document_memories(store, _normalized(), _PROV, "dom", "/dir")
        assert out["summary_memory_id"] is None
        assert out["section_memory_ids"] == []
        # Exact formatted messages — the failing exception text AND the section
        # heading must reach the log (guards the log-arg wiring).
        msgs = [r.getMessage() for r in caplog.records]
        assert "ingest_document summary insert failed: db down" in msgs
        assert "ingest_document section insert failed (Intro): db down" in msgs
