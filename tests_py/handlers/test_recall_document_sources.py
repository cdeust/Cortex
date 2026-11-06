"""A recalled document segment names its source file and version.

source: issue #713 (slice 2)
"""

from __future__ import annotations

import asyncio

from mcp_server.core.document_model import (
    DocumentProvenance,
    document_provenance_dedup_tag,
    parse_document_provenance_dedup_tag,
)
from mcp_server.core.document_reference import annotate_document_sources
from mcp_server.handlers import ingest_document
from mcp_server.handlers.recall import handler as recall_handler


def test_dedup_tag_round_trips_a_path_holding_colon_and_at():
    prov = DocumentProvenance(
        source=r"C:\docs\team@corp\guide.docx",
        version="0123456789abcdef",
        source_kind="docx",
    )
    tag = document_provenance_dedup_tag(prov)
    assert parse_document_provenance_dedup_tag(tag) == prov


def test_other_tags_parse_to_none():
    for tag in [
        "document",
        "doc-src:docx:/a.docx",
        "doc-ingest:",
        "doc-ingest:docx",
        "doc-ingest:docx:/a.docx",  # no version
        "doc-ingest:docx:/a.docx@",  # empty version
        "doc-ingest:docx:@v1",  # empty source
        "doc-ingest::/a.docx@v1",  # empty kind
    ]:
        assert parse_document_provenance_dedup_tag(tag) is None, tag


def test_hit_without_document_tag_gets_no_key():
    hits = [{"tags": ["python", "doc-src:docx:/a.docx"]}, {"tags": None}]
    annotate_document_sources(hits)
    assert all("document_sources" not in hit for hit in hits)


def test_two_versions_are_both_listed():
    hit = {"tags": ["doc-ingest:docx:/a.docx@v1", "doc-ingest:docx:/a.docx@v2"]}
    annotate_document_sources([hit])
    assert [ref["version"] for ref in hit["document_sources"]] == ["v1", "v2"]


async def _no_wiki(root, rel_path, content, *, mode="create", **_kw):
    return {"path": rel_path, "created": True, "bytes_written": len(content)}


def test_recall_returns_source_and_version_of_an_ingested_segment(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(ingest_document, "WIKI_ROOT", tmp_path / "wiki")
    monkeypatch.setattr(ingest_document, "write_governed_page", _no_wiki)
    page = tmp_path / "kestrel-runbook.xml"
    page.write_text(
        "<h1>Kestrel failover</h1><p>drain the quoxel queue before failover</p>",
        encoding="utf-8",
    )
    out = asyncio.run(ingest_document.handler({"path": str(page)}))
    assert out["ingested"] is True

    result = asyncio.run(
        recall_handler({"query": "quoxel queue failover", "max_results": 5})
    )
    hit = next(m for m in result["memories"] if "quoxel" in m["content"])
    assert hit["document_sources"] == [
        {
            "source": str(page),
            "version": out["version"],
            "source_kind": "confluence-export",
        }
    ]
