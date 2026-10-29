"""Issue #714: receipts of an obsolete normalized output never block a resume.

A same-version request whose normalized output differs (``title`` override,
normalizer or redaction change) leaves receipts no expected component can
consume. They are retired (``is_stale``) instead of being counted against the
bounded receipt read. Real SQLite store, no fake, except the loop-guard case.
"""

from __future__ import annotations

import pytest

from mcp_server.core.document_model import (
    DocumentProvenance,
    document_provenance_dedup_tag,
)
from mcp_server.core.document_normalizer import NormalizedDocument, SectionMemory
from mcp_server.handlers import ingest_document
from mcp_server.handlers.ingest_document_writers import (
    DocumentMemoryContext,
    write_document_memories,
)
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from tests_py.handlers.test_ingest_document import _FakeStore, _RecordingWrite

_PROV = DocumentProvenance("/drift.xml", "v1", "confluence-export")


@pytest.fixture
def store(tmp_path):
    sqlite = SqliteMemoryStore(str(tmp_path / "memory.sqlite"))
    yield sqlite
    sqlite.close()


@pytest.fixture
def document(monkeypatch, tmp_path, store):
    path = tmp_path / "page.xml"
    path.write_text("<h1>Doc</h1><p>first</p><h2>Next</h2><p>second</p>")
    monkeypatch.setattr(ingest_document, "WIKI_ROOT", tmp_path / "wiki")
    monkeypatch.setattr(ingest_document, "_get_store", lambda: store)
    monkeypatch.setattr(ingest_document, "write_governed_page", _RecordingWrite())
    return path


def _live(store, prov: DocumentProvenance) -> list[dict]:
    tag = document_provenance_dedup_tag(prov)
    return store.get_memories_by_tag(tag, limit=100, heads_only=False)


def _prov_of(result: dict) -> DocumentProvenance:
    return DocumentProvenance(
        result["source"], result["version"], result["source_kind"]
    )


@pytest.mark.asyncio
async def test_title_override_retires_the_obsolete_summary(document, store):
    first = await ingest_document.handler({"path": str(document)})
    renamed = await ingest_document.handler({"path": str(document), "title": "Renamed"})
    assert renamed["ingested"] is True, renamed["failures"]
    assert renamed["section_memory_ids"] == first["section_memory_ids"]
    assert renamed["retired_receipt_ids"] == [first["summary_memory_id"]]
    assert len(_live(store, _prov_of(first))) == 3

    back = await ingest_document.handler({"path": str(document)})
    assert back["ingested"] is True, back["failures"]
    assert back["retired_receipt_ids"] == [renamed["summary_memory_id"]]
    again = await ingest_document.handler({"path": str(document)})
    assert again["idempotent_skip"] is True
    assert again["retired_receipt_ids"] == []
    assert again["summary_memory_id"] == back["summary_memory_id"]
    assert len(_live(store, _prov_of(first))) == 3


def _output(*sections: str, summary: str = "summary") -> NormalizedDocument:
    return NormalizedDocument(
        wiki_rel_path="documents/drift.md",
        wiki_markdown="# Drift\n",
        summary=summary,
        section_memories=[SectionMemory("S", body) for body in sections],
    )


def _write(store, normalized: NormalizedDocument) -> dict:
    context = DocumentMemoryContext(store, _PROV, "documents", "/")
    return write_document_memories(context, normalized)


def test_normalizer_drift_with_changed_section_count_keeps_resuming(store):
    outputs = [
        _output("a", "b"),
        _output("c", "d", "e", summary="summary v2"),
        _output("f", summary="summary v3"),
        _output("f", summary="summary v3"),
    ]
    results = [_write(store, normalized) for normalized in outputs]
    for normalized, result in zip(outputs, results, strict=True):
        assert result["failures"] == {}
        assert (
            len(result["completed_components"]) == len(normalized.section_memories) + 1
        )
    assert len(results[1]["retired_receipt_ids"]) == 3
    assert len(results[2]["retired_receipt_ids"]) == 4
    assert results[3]["retired_receipt_ids"] == []
    assert results[3]["reused_components"] == ["summary", "section:0"]
    assert len(_live(store, _PROV)) == 2


def test_superseded_carrier_with_matching_content_is_consumed(store):
    first = _write(store, _output("a", "b"))
    carrier = first["section_memory_ids"][0]
    new_id, _ = store.supersede_atomic(
        {"content": "corrected a", "source": "user", "domain": "d", "heat": 0.5},
        carrier,
    )
    assert new_id is not None
    again = _write(store, _output("a", "b"))
    assert again["retired_receipt_ids"] == []
    assert again["section_memory_ids"] == first["section_memory_ids"]
    assert again["reused_components"] == ["summary", "section:0", "section:1"]


@pytest.mark.parametrize("source", ["user", "cls-consolidation"])
def test_rows_not_written_by_ingestion_are_neither_retired_nor_counted(store, source):
    tag = document_provenance_dedup_tag(_PROV)
    note = store.insert_memory(
        {"content": "other", "tags": [tag, "section"], "source": source}
    )
    first = _write(store, _output("a"))
    again = _write(store, _output("a"))
    for result in (first, again):
        assert result["failures"] == {}
        assert result["retired_receipt_ids"] == []
    assert again["reused_components"] == ["summary", "section:0"]
    assert note in {row["id"] for row in _live(store, _PROV)}


def test_compressed_section_remains_its_receipt(store):
    first = _write(store, _output("a long section body", "b"))
    section = first["section_memory_ids"][0]
    original = store.get_memory(section)["content"]
    store.update_memory_compression(section, "gist", None, 1, original)
    store.update_memory_compression(section, "tag", None, 2)
    again = _write(store, _output("a long section body", "b"))
    assert again["retired_receipt_ids"] == []
    assert again["section_memory_ids"] == first["section_memory_ids"]
    assert again["reused_components"] == ["summary", "section:0", "section:1"]


class _StaleIgnoringStore(_FakeStore):
    """A backend whose tag read keeps returning rows it was told are stale."""

    def mark_memory_stale(self, memory_id: int, stale: bool = True) -> None:
        del memory_id, stale


def test_store_that_keeps_returning_retired_rows_fails_closed():
    fake = _StaleIgnoringStore()
    tag = document_provenance_dedup_tag(_PROV)
    fake.insert_memory(
        {
            "content": "old summary",
            "tags": [tag, "summary"],
            "source": f"ingest_document:{_PROV.source}",
        }
    )
    result = _write(fake, _output("a"))
    assert "memory_lookup" in result["failures"]
    assert result["completed_components"] == []
    assert len(fake.memories) == 1
