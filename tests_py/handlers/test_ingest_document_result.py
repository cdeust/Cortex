"""_ingestion_result never reports a document complete that is not (issue #714).

Exact ``ingested`` / ``status`` / ``reason`` values for a fresh complete ingest,
a partial one with a failure, and a partial one where a component is missing
without any recorded failure.
"""

from __future__ import annotations

from mcp_server.core.document_model import DocumentAttachment
from mcp_server.core.document_normalizer import NormalizedDocument
from mcp_server.handlers.ingest_document import _ingestion_result


def _normalized() -> NormalizedDocument:
    return NormalizedDocument(
        wiki_rel_path="documents/d.md",
        wiki_markdown="# D\n",
        summary="s",
        attachments=[DocumentAttachment(1, "rId1", "H")],
    )


def _written(completed: list[str], failures: dict[str, str]) -> dict:
    return {
        "expected_components": ["summary"],
        "completed_components": completed,
        "reused_components": [],
        "failures": failures,
        "summary_memory_id": None,
        "section_memory_ids": [],
        "retired_receipt_ids": [],
    }


def _verdict(out: dict) -> tuple:
    return out["ingested"], out["status"], out["reason"], out["idempotent_skip"]


def test_a_fresh_complete_ingest_reads_complete():
    out = _ingestion_result(
        _normalized(), _written(["summary"], {}), (True, False, None)
    )
    assert _verdict(out) == (True, "complete", "complete", False)
    assert out["images_skipped"] == 1


def test_a_failed_component_reads_incomplete():
    written = _written([], {"summary": "boom"})
    out = _ingestion_result(_normalized(), written, (True, False, None))
    assert _verdict(out) == (False, "partial", "document_ingestion_incomplete", False)
    assert out["failures"] == {"summary": "boom"}


def test_a_missing_component_without_failure_is_still_incomplete():
    out = _ingestion_result(_normalized(), _written([], {}), (True, False, None))
    assert _verdict(out) == (False, "partial", "document_ingestion_incomplete", False)
