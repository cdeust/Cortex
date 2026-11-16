"""A wiki page traces back to the document segments and versions it cites.

source: issue #713 (slice 3)
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from mcp_server.core.document_reference import cited_memory_sources
from mcp_server.handlers import ingest_document, wiki_read, wiki_write
from mcp_server.handlers.wiki_read_sources import (
    PAGE_NOT_INDEXED,
    attach_page_sources,
)

_DOC_TAG = "doc-ingest:docx:/a.docx@v1"


def test_missing_memory_is_kept_and_marked_in_citation_order():
    memories = {
        7: {"tags": [_DOC_TAG]},
        3: {"tags": ["python"]},
    }
    refs = cited_memory_sources([7, 42, 3], memories)
    assert refs == [
        {
            "memory_id": 7,
            "document_sources": [
                {"source": "/a.docx", "version": "v1", "source_kind": "docx"}
            ],
        },
        {"memory_id": 42, "missing": True},
        {"memory_id": 3},
    ]


def _page_md(title: str) -> str:
    return (
        f"---\nid: 01J00000000000000000000713\ntitle: {title}\n"
        "kind: explanation\nlifecycle: seedling\naudience:\n  - developer\n"
        f"provenance: human\n---\n\n# {title}\n\nSynthesis.\n"
    )


async def _no_wiki(root, rel_path, content, *, mode="create", **_kw):
    return {"path": rel_path, "created": True, "bytes_written": len(content)}


def _ingest(tmp_path: Path, name: str, body: str) -> dict:
    doc = tmp_path / name
    doc.write_text(body, encoding="utf-8")
    out = asyncio.run(ingest_document.handler({"path": str(doc)}))
    assert out["ingested"] is True
    return {"path": str(doc), **out}


def _two_documents_and_a_page(monkeypatch, tmp_path):
    """Ingest two documents and write one page citing both summaries."""
    wiki_root = tmp_path / "wiki"
    monkeypatch.setattr(ingest_document, "WIKI_ROOT", wiki_root)
    monkeypatch.setattr(ingest_document, "write_governed_page", _no_wiki)
    monkeypatch.setattr(wiki_write, "WIKI_ROOT", str(wiki_root))
    monkeypatch.setattr(wiki_read, "WIKI_ROOT", str(wiki_root))
    first = _ingest(
        tmp_path, "osprey.xml", "<h1>Osprey</h1><p>rotate the zelkova keys</p>"
    )
    second = _ingest(
        tmp_path, "heron.xml", "<h1>Heron</h1><p>flush the vantor cache</p>"
    )
    cited = [first["summary_memory_id"], second["summary_memory_id"]]

    written = asyncio.run(
        wiki_write.handler(
            {
                "path": "notes/key-rotation.md",
                "content": _page_md("Key rotation"),
                "memory_ids": cited,
            }
        )
    )
    assert written["citations_written"] == 2

    return wiki_root, (first, second), cited


def test_wiki_read_returns_each_cited_segment_with_its_source(monkeypatch, tmp_path):
    wiki_root, docs, cited = _two_documents_and_a_page(monkeypatch, tmp_path)
    page = asyncio.run(wiki_read.handler({"path": "notes/key-rotation.md"}))
    assert "sources_unavailable" not in page
    assert page["path"] == "notes/key-rotation.md"
    assert page["root"] == str(wiki_root)
    assert page["redirect_chain"] == []
    assert page["content"].endswith("# Key rotation\n\nSynthesis.\n")
    assert [ref["memory_id"] for ref in page["sources"]] == cited
    assert [ref["document_sources"] for ref in page["sources"]] == [
        [
            {
                "source": doc["path"],
                "version": doc["version"],
                "source_kind": "confluence-export",
            }
        ]
        for doc in docs
    ]


def test_page_with_no_index_row_says_so(monkeypatch, tmp_path):
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "loose.md").write_text(_page_md("Loose"), encoding="utf-8")
    monkeypatch.setattr(wiki_read, "WIKI_ROOT", str(tmp_path))
    page = asyncio.run(wiki_read.handler({"path": "notes/loose.md"}))
    assert "sources" not in page
    assert page["sources_unavailable"] == PAGE_NOT_INDEXED


def test_store_error_is_named_not_turned_into_an_empty_trace():
    def _down():
        raise RuntimeError("store down")

    resp = attach_page_sources({"path": "p.md"}, "p.md", _down)
    assert resp == {"path": "p.md", "sources_unavailable": "RuntimeError: store down"}


def test_store_error_is_logged_with_the_page_and_its_traceback(caplog):
    def _down():
        raise RuntimeError("store down")

    with caplog.at_level("WARNING", logger="mcp_server.handlers.wiki_read_sources"):
        attach_page_sources({}, "notes/p.md", _down)
    (record,) = caplog.records
    assert record.levelname == "WARNING"
    assert record.getMessage() == "wiki_read source trace failed for notes/p.md"
    assert record.exc_info is not None and record.exc_info[0] is RuntimeError
