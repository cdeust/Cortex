"""Issue #714: partial receipts and restart recovery of committed components."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys

import pytest

from mcp_server.handlers import ingest_document
from mcp_server.core.document_model import (
    DocumentProvenance,
    document_provenance_dedup_tag,
)
from mcp_server.core.document_normalizer import NormalizedDocument, SectionMemory
from mcp_server.handlers.ingest_document_writers import (
    DocumentMemoryContext,
    write_document_memories,
)
from tests_py.handlers.test_ingest_document import _FakeStore, _RecordingWrite


@pytest.fixture
def document(monkeypatch, tmp_path):
    path = tmp_path / "page.xml"
    path.write_text("<h1>Doc</h1><p>first</p><h2>Next</h2><p>second</p>")
    store = _FakeStore()
    write = _RecordingWrite()
    monkeypatch.setattr(ingest_document, "WIKI_ROOT", tmp_path / "wiki")
    monkeypatch.setattr(ingest_document, "_get_store", lambda: store)
    monkeypatch.setattr(ingest_document, "write_governed_page", write)
    return path, store, write


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", ["wiki", "summary", "section:0", "section:1"])
async def test_partial_result_then_resume_only_missing(document, monkeypatch, failed):
    path, store, write = document
    insert = store.insert_memory
    count = 0

    def failing_insert(record):
        nonlocal count
        component = ["summary", "section:0", "section:1"][count]
        count += 1
        if component == failed:
            raise RuntimeError("injected failure")
        return insert(record)

    async def failing_wiki(*args, **kwargs):
        return {"error": "injected failure"}

    monkeypatch.setattr(store, "insert_memory", failing_insert)
    if failed == "wiki":
        monkeypatch.setattr(ingest_document, "write_governed_page", failing_wiki)
    partial = await ingest_document.handler({"path": str(path)})
    expected = ["wiki", "summary", "section:0", "section:1"]
    assert partial["ingested"] is False
    assert partial["status"] == "partial"
    assert partial["expected_components"] == expected
    assert partial["completed_components"] == [c for c in expected if c != failed]
    assert partial["failures"] == {failed: "injected failure"}
    assert partial["idempotent_skip"] is False
    prior_ids = {row["id"] for row in store.memories}
    monkeypatch.setattr(store, "insert_memory", insert)
    monkeypatch.setattr(ingest_document, "write_governed_page", write)
    resumed = await ingest_document.handler({"path": str(path)})
    assert resumed["ingested"] is True
    assert resumed["completed_components"] == expected
    assert resumed["failures"] == {}
    assert len(store.memories) == 3
    assert prior_ids <= {row["id"] for row in store.memories}
    assert len(write.calls) == 1


@pytest.mark.asyncio
async def test_wiki_exception_is_public_partial_receipt(document, monkeypatch):
    path, store, _ = document

    async def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(ingest_document, "write_governed_page", fail)
    result = await ingest_document.handler({"path": str(path)})
    assert result["ingested"] is False
    assert result["failures"] == {"wiki": "disk full"}
    assert result["completed_components"] == ["summary", "section:0", "section:1"]
    assert len(store.memories) == 3


@pytest.mark.asyncio
async def test_unreadable_wiki_is_not_overwritten(document, monkeypatch):
    path, _, write = document

    def fail(*args):
        raise OSError("permission denied")

    monkeypatch.setattr(ingest_document, "read_page", fail)
    result = await ingest_document.handler({"path": str(path)})
    assert result["failures"] == {"wiki": "permission denied"}
    assert result["wiki_path"] is None
    assert write.calls == []


@pytest.mark.asyncio
async def test_missing_or_changed_wiki_is_repaired_without_memory_duplicates(document):
    path, store, write = document
    original = await ingest_document.handler({"path": str(path)})
    page = ingest_document.WIKI_ROOT / original["wiki_path"]
    for replacement in [None, "other source/version"]:
        if replacement is None:
            page.unlink()
        else:
            page.write_text(replacement)
        repaired = await ingest_document.handler({"path": str(path)})
        assert repaired["ingested"] is True
        assert repaired["idempotent_skip"] is False
        assert repaired["summary_memory_id"] == original["summary_memory_id"]
        assert repaired["section_memory_ids"] == original["section_memory_ids"]
    assert len(store.memories) == 3
    assert len(write.calls) == 3


def _normalized():
    return NormalizedDocument(
        wiki_rel_path="documents/repeated.md",
        wiki_markdown="# Repeated\n",
        summary="summary",
        section_memories=[SectionMemory("Same", "body"), SectionMemory("Same", "body")],
    )


def _provenance():
    return DocumentProvenance("/document.xml", "v1", "confluence-export")


def test_legacy_summary_missing_sections_and_identical_occurrences_resume():
    store = _FakeStore()
    normalized = _normalized()
    prov = _provenance()
    tag = document_provenance_dedup_tag(prov)
    own = f"ingest_document:{prov.source}"
    summary_id = store.insert_memory(
        {"content": normalized.summary, "tags": [tag, "summary"], "source": own}
    )
    section_id = store.insert_memory(
        {"content": "body", "tags": [tag, "section"], "source": own}
    )
    result = write_document_memories(
        DocumentMemoryContext(store, prov, "documents", "/"), normalized
    )
    assert result["summary_memory_id"] == summary_id
    assert result["section_memory_ids"][0] == section_id
    assert result["section_memory_ids"][1] != section_id
    assert result["completed_components"] == ["summary", "section:0", "section:1"]
    assert len(store.memories) == 3
    again = write_document_memories(
        DocumentMemoryContext(store, prov, "documents", "/"), normalized
    )
    assert again["section_memory_ids"] == result["section_memory_ids"]
    assert len(store.memories) == 3


def test_failed_lookup_writes_nothing(monkeypatch):
    store = _FakeStore()

    def fail(*args, **kwargs):
        raise OSError("database unavailable")

    monkeypatch.setattr(store, "get_memories_by_tag", fail)
    result = write_document_memories(
        DocumentMemoryContext(store, _provenance(), "d", "/"), _normalized()
    )
    assert result["failures"] == {"memory_lookup": "database unavailable"}
    assert result["completed_components"] == []
    assert store.memories == []


def test_excess_rows_fail_closed():
    store = _FakeStore()
    tag = document_provenance_dedup_tag(_provenance())
    for _ in range(4):
        store.insert_memory(
            {
                "content": "summary",
                "tags": [tag, "summary"],
                "source": f"ingest_document:{_provenance().source}",
            }
        )
    result = write_document_memories(
        DocumentMemoryContext(store, _provenance(), "d", "/"), _normalized()
    )
    assert "excess component rows" in result["failures"]["memory_lookup"]
    assert len(store.memories) == 4


# Child exits immediately after a real atomic page write or committed memory,
# then a fresh interpreter reconstructs the handler and SQLite store.
_CHILD = r"""
import asyncio
import json
import os
import sys
from pathlib import Path
from mcp_server.handlers import ingest_document as handler
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from mcp_server.infrastructure.wiki_store import write_page

root, crash = Path(sys.argv[1]), sys.argv[2]
store = SqliteMemoryStore(str(root / "memory.sqlite"))
handler._get_store = lambda: store
handler.WIKI_ROOT = root / "wiki"
insert = store.insert_memory
count = 0

def insert_and_crash(record):
    global count
    memory_id = insert(record)
    component = ["summary", "section:0", "section:1"][count]
    count += 1
    if component == crash:
        os._exit(23)
    return memory_id

async def write_and_crash(root, path, content, **kwargs):
    write_page(root, path, content, mode="replace")
    if crash == "wiki":
        os._exit(23)
    return {"path": path}

store.insert_memory = insert_and_crash
handler.write_governed_page = write_and_crash
result = asyncio.run(handler.handler({"path": str(root / "page.xml")}))
store.close()
print(json.dumps(result))
"""


def _child(root, crash):
    env = dict(os.environ, CORTEX_RERANKER_OFFLINE="1")
    return subprocess.run(
        [sys.executable, "-c", _CHILD, str(root), crash],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


@pytest.mark.parametrize("boundary", ["wiki", "summary", "section:0", "section:1"])
@pytest.mark.parametrize("variant", ["distinct", "repeated", "redacted"])
def test_real_process_restart_after_each_committed_boundary(
    tmp_path, boundary, variant
):
    path = tmp_path / "page.xml"
    path.write_text("<h1>Doc</h1><p>first</p><h2>Next</h2><p>second</p>")
    if variant == "repeated":
        path.write_text("<h1>Doc</h1><p>first</p><h2>Doc</h2><p>first</p>")
    if variant == "redacted":
        path.write_text(
            "<h1>Doc</h1><p>password=fixture-only-password</p>"
            "<h2>Next</h2><p>second</p>"
        )
    stopped = _child(tmp_path, boundary)
    assert stopped.returncode == 23, stopped.stderr
    with sqlite3.connect(tmp_path / "memory.sqlite") as conn:
        before = conn.execute("SELECT id FROM memories").fetchall()
    resumed = _child(tmp_path, "")
    assert resumed.returncode == 0, resumed.stderr
    result = json.loads(resumed.stdout)
    assert result["ingested"] is True
    assert result["completed_components"] == [
        "wiki",
        "summary",
        "section:0",
        "section:1",
    ]
    assert result["failures"] == {}
    with sqlite3.connect(tmp_path / "memory.sqlite") as conn:
        after = conn.execute("SELECT id FROM memories").fetchall()
    assert len(after) == 3
    assert set(before) <= set(after)
    repeated = _child(tmp_path, "")
    assert repeated.returncode == 0, repeated.stderr
    skipped = json.loads(repeated.stdout)
    assert skipped["idempotent_skip"] is True
    assert skipped["summary_memory_id"] == result["summary_memory_id"]
    assert skipped["section_memory_ids"] == result["section_memory_ids"]
    with sqlite3.connect(tmp_path / "memory.sqlite") as conn:
        assert conn.execute("SELECT id FROM memories").fetchall() == after
