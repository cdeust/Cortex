"""A wiki page traces back to the document segments and versions it cites.

source: issue #713 (slice 3)
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from mcp_server.core.document_reference import cited_memory_sources
from mcp_server.handlers import ingest_document, wiki_read, wiki_write
from mcp_server.core.response_budget import serialized_length
from mcp_server.handlers.wiki_read_sources import (
    PAGE_NOT_INDEXED,
    STORE_ERROR,
    attach_page_sources,
    fit_sources,
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


def test_store_error_is_named_without_its_text():
    def _down():
        raise RuntimeError("PostgreSQL connection failed (url=postgresql://u:pw@h/db)")

    resp = attach_page_sources({"path": "p.md"}, "p.md", _down)
    assert resp == {"path": "p.md", "sources_unavailable": STORE_ERROR}


def test_content_keeps_priority_over_the_trace():
    sources = [{"memory_id": i} for i in range(50)]
    resp = {"content": "x" * 200, "sources": sources}
    fit_sources(resp, serialized_length({"content": "x" * 200}) + 100)
    assert resp["content"] == "x" * 200
    assert resp["sources_truncated"] is True
    assert resp["sources_total"] == 50
    assert 0 < len(resp["sources"]) < 50
    assert serialized_length(resp) <= serialized_length({"content": "x" * 200}) + 100
    kept = len(resp["sources"])
    assert resp["sources"] == [{"memory_id": i} for i in range(kept)]


def test_a_trace_that_fits_is_left_whole():
    resp = {"content": "x", "sources": [{"memory_id": 1}]}
    fit_sources(resp, 10_000)
    assert resp == {"content": "x", "sources": [{"memory_id": 1}]}


def test_store_error_is_logged_with_the_page_and_its_traceback(caplog):
    def _down():
        raise RuntimeError("store down")

    with caplog.at_level("WARNING", logger="mcp_server.handlers.wiki_read_sources"):
        attach_page_sources({}, "notes/p.md", _down)
    (record,) = caplog.records
    assert record.levelname == "WARNING"
    assert record.getMessage() == "wiki_read source trace failed for notes/p.md"
    assert record.exc_info is not None and record.exc_info[0] is RuntimeError


def test_a_trace_exactly_at_the_budget_is_left_whole():
    resp = {"content": "x", "sources": [{"memory_id": 1}, {"memory_id": 2}]}
    fit_sources(resp, serialized_length(resp))
    assert resp == {"content": "x", "sources": [{"memory_id": 1}, {"memory_id": 2}]}


def test_the_cut_stops_as_soon_as_the_payload_fits_exactly():
    # each entry outweighs the two flags, so dropping one is enough to fit
    sources = [{"memory_id": i, "pad": "y" * 100} for i in range(5)]
    expected = {
        "content": "x",
        "sources": sources[:-1],
        "sources_truncated": True,
        "sources_total": 5,
    }
    resp = {"content": "x", "sources": list(sources)}
    fit_sources(resp, serialized_length(expected))
    assert resp == expected


def test_an_empty_trace_is_never_flagged():
    resp = {"content": "x" * 50, "sources": []}
    fit_sources(resp, 1)
    assert resp == {"content": "x" * 50, "sources": []}


def test_the_cut_serializes_the_whole_payload_twice_not_once_per_entry(monkeypatch):
    from mcp_server.handlers import wiki_read_sources

    sources = [{"memory_id": i, "pad": "y" * 20} for i in range(400)]
    resp = {"content": "x" * 2000, "sources": sources}
    whole: list[int] = []

    def _counting(payload):
        if payload is resp:
            whole.append(1)
        return serialized_length(payload)

    monkeypatch.setattr(wiki_read_sources, "serialized_length", _counting)
    fit_sources(resp, 4000)
    assert len(whole) == 2  # the fit check, then the size before the cut
    assert serialized_length(resp) <= 4000
    assert serialized_length(resp) > 4000 - serialized_length(sources[0]) - 1


def test_the_running_size_stays_exact_down_to_the_last_entry():
    # a budget below the payload without any entry drops them all; the
    # arithmetic for the last (comma-less) entry must land on the real size.
    # Each entry outweighs the two flags and has a distinct non-ASCII length.
    sources = [{"memory_id": i, "note": "é" * (60 + i)} for i in range(6)]
    resp = {"content": "x" * 30, "sources": list(sources)}
    fit_sources(resp, 1)
    assert resp["sources"] == []
    assert resp["sources_total"] == 6
    for kept in range(1, 6):
        expected = {
            "content": "x",
            "sources": sources[:kept],
            "sources_truncated": True,
            "sources_total": 6,
        }
        resp = {"content": "x", "sources": list(sources)}
        fit_sources(resp, serialized_length(expected))
        assert resp == expected
