"""Ingest duplicate-prevention lookups still see a superseded carrier.

ADR-1100: ``find_existing_memory`` (findings) and ``already_ingested``
(documents) are idempotency checks. A corrected fact is a new row from
``remember(supersedes_id=...)`` and need not carry the dedup tag, so a lookup
that reads chain heads misses the retracted carrier and the next ingestion
inserts the retracted text again as a fresh head. Real SQLite store, no fake.
"""

from __future__ import annotations

import pytest

from mcp_server.core.document_model import DocumentProvenance
from mcp_server.core.document_normalizer import NormalizedDocument, SectionMemory
from mcp_server.handlers.ingest_document_writers import (
    already_ingested,
    write_document_memories,
)
from mcp_server.handlers.ingest_findings_artifacts import FindingRecord
from mcp_server.handlers.ingest_findings_writers import (
    find_existing_memory,
    write_finding_memory,
)
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

_CORRECTION = {"source": "user", "domain": "ingest-dedup", "heat": 0.5}


@pytest.fixture
def store():
    return SqliteMemoryStore()


def _supersede(store: SqliteMemoryStore, old_id: int, content: str) -> int:
    new_id, head = store.supersede_atomic({**_CORRECTION, "content": content}, old_id)
    assert new_id is not None and head == old_id
    return new_id


def _finding() -> FindingRecord:
    return FindingRecord(
        run_id="run1",
        finding_id="f1",
        verified=True,
        title="Symbol X leaks memory",
        description="Root cause: unbounded growth in cache Y.",
        refined_rel_path="findings/f1/stage-1.refined.json",
        file_paths=[],
        receipts=[],
        source_path=None,
    )


def test_a_superseded_finding_is_not_written_again(store):
    memory_id, created = write_finding_memory(store, _finding())
    assert created
    _supersede(store, memory_id, "corrected: the leak was in cache Z")
    rows_before = store.count_memories()

    assert find_existing_memory(store, "run1", "f1") == memory_id
    assert write_finding_memory(store, _finding()) == (memory_id, False)
    assert store.count_memories() == rows_before


def test_a_superseded_document_summary_is_not_ingested_again(store):
    prov = DocumentProvenance(source="/d.docx", version="v1", source_kind="docx")
    normalized = NormalizedDocument(
        wiki_rel_path="documents/d.md",
        wiki_markdown="# D\n",
        summary="Document ingested: 'D'.",
        section_memories=[SectionMemory("Intro", "[Intro]\n\nbody")],
        notices=[],
        image_count=0,
    )
    written = write_document_memories(store, normalized, prov, "ingest-dedup", "dir")
    carriers = {written["summary_memory_id"], *written["section_memory_ids"]}
    for carrier in carriers:
        _supersede(store, carrier, f"corrected {carrier}, no dedup tag")

    # every row that carried the dedup tag is now retracted: the lookup must
    # still report the prior ingestion, or the document is ingested twice
    assert already_ingested(store, prov) in carriers
