"""Resumable document memory writes using durable provenance rows.

source: issue #714; ADR-0409 (existing per-memory commit boundary).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

from mcp_server.core.document_model import (
    DocumentProvenance,
    document_provenance_dedup_tag,
    document_provenance_source_tag,
)
from mcp_server.core.document_normalizer import NormalizedDocument

from mcp_server.observability import silent_failure
from mcp_server.shared.redaction_gate import redact_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DocumentMemoryContext:
    """Composition-root dependencies for one source/version write.

    source: issue #714
    """

    store: Any
    provenance: DocumentProvenance
    domain: str
    directory: str


@dataclass
class _WriteProgress:
    """Receipts consumed and produced by this attempt."""

    rows: list[dict[str, Any]]
    result: dict[str, Any]


def content_version(raw: str) -> str:
    """Stable version token for the document text.

    source: ADR-0409
    """
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _expected_receipts(normalized: NormalizedDocument) -> set[tuple[str, str]]:
    """(role, stored content) pairs the current normalized output can consume."""
    expected = {("summary", redact_text(normalized.summary))}
    expected.update(
        ("section", redact_text(memory.content))
        for memory in normalized.section_memories
    )
    return expected


def _is_obsolete(
    row: dict[str, Any], own_source: str, expected: set[tuple[str, str]]
) -> bool:
    """An ingest-authored receipt of another normalized output of this version."""
    tags = row.get("tags", [])
    role = "summary" if "summary" in tags else "section" if "section" in tags else ""
    if not role or row.get("source") != own_source:
        return False
    return (role, row.get("content")) not in expected


def _existing_components(
    store: Any, normalized: NormalizedDocument, prov: DocumentProvenance
) -> tuple[list[dict[str, Any]], list[int]]:
    """Read durable receipts before writing; lookup failure must prevent duplicates.

    Receipts left by another normalized output of the same version (title
    override, normalizer or redaction change) are retired with ``is_stale``,
    which the tag read already excludes, so they are never counted.
    """
    tag = redact_text(document_provenance_dedup_tag(prov))
    own_source = redact_text(f"ingest_document:{prov.source}")
    expected = _expected_receipts(normalized)
    # source: issue #714 — one summary + all sections + one overflow sentinel.
    limit = len(normalized.section_memories) + 2
    retired: list[int] = []
    while True:
        rows = store.get_memories_by_tag(tag, limit=limit, heads_only=False)
        obsolete = [
            row["id"] for row in rows if _is_obsolete(row, own_source, expected)
        ]
        if not obsolete:
            break
        if set(obsolete) & set(retired):
            raise ValueError("store still returns retired receipts; refusing resume")
        for memory_id in obsolete:
            store.mark_memory_stale(memory_id)
        retired.extend(obsolete)
    if len(rows) >= limit:
        raise ValueError(
            "document has excess component rows; refusing ambiguous resume"
        )
    # Stable order assigns identical section occurrences the same receipts on retry.
    current = sorted(
        (
            row
            for row in rows
            if tag in row.get("tags", []) and row.get("id") is not None
        ),
        key=lambda row: row["id"],
    )
    return current, retired


def _take_existing(rows: list[dict[str, Any]], role: str, content: str) -> int | None:
    """Consume one matching row, preserving repeated identical section occurrences."""
    content = redact_text(content)
    for index, row in enumerate(rows):
        if role in row.get("tags", []) and row.get("content") == content:
            return rows.pop(index)["id"]
    return None


def _record(content: str, role: str, context: DocumentMemoryContext) -> dict[str, Any]:
    """Keep the existing summary/section storage policy and provenance.

    source: ADR-0409
    """
    prov = context.provenance
    summary = role == "summary"
    return {
        "content": redact_text(content),
        "tags": [
            "document",
            "ingest",
            prov.source_kind,
            document_provenance_dedup_tag(prov),
            document_provenance_source_tag(prov),
            role,
        ],
        "source": f"ingest_document:{prov.source}",
        "domain": context.domain,
        "directory_context": context.directory,
        "importance": 0.8 if summary else 0.5,
        "heat": 0.9 if summary else 0.6,
        "confidence": 0.9,
        "is_protected": summary,
        "write_class": "mechanical",
    }


def _write_component(
    context: DocumentMemoryContext,
    progress: _WriteProgress,
    record: dict[str, Any],
    component: str,
) -> int | None:
    """Reuse a committed row or attempt one insert, exposing its failure."""
    result = progress.result
    role = "summary" if component == "summary" else "section"
    memory_id = _take_existing(progress.rows, role, record["content"])
    if memory_id is not None:
        result["reused_components"].append(component)
    else:
        try:
            memory_id = context.store.insert_memory(record)
            if memory_id is None:
                raise ValueError("insert returned no memory id")
        except Exception as exc:  # noqa: BLE001 — storage boundary; public failure receipt
            result["failures"][component] = str(exc)
            logger.warning("ingest_document %s insert failed: %s", component, exc)
            return None
    result["completed_components"].append(component)
    return memory_id


def write_document_memories(
    context: DocumentMemoryContext,
    normalized: NormalizedDocument,
) -> dict[str, Any]:
    """Resume missing components from durable rows, including legacy partial ingests.

    Wiki and individual memories commit independently. No process-local completion
    marker is authoritative. A retry consumes existing rows once per expected
    occurrence; receipts of another normalized output of this version are
    retired first. A failed receipt lookup writes nothing. Intended for sequential
    retries, not a distributed concurrent-ingestion uniqueness guarantee.
    source: issue #714
    """
    expected = [
        "summary",
        *(f"section:{index}" for index in range(len(normalized.section_memories))),
    ]
    result: dict[str, Any] = {
        "summary_memory_id": None,
        "section_memory_ids": [],
        "expected_components": expected,
        "completed_components": [],
        "reused_components": [],
        "retired_receipt_ids": [],
        "failures": {},
    }
    try:
        rows, retired = _existing_components(
            context.store, normalized, context.provenance
        )
    except Exception as exc:  # noqa: BLE001 — storage boundary; no duplicate-prone fallback
        silent_failure.note("ingest_document.memory_lookup", exc)
        result["failures"]["memory_lookup"] = str(exc)
        return result
    result["retired_receipt_ids"] = retired
    _write_missing_memories(context, normalized, _WriteProgress(rows, result))
    return result


def _write_missing_memories(
    context: DocumentMemoryContext,
    normalized: NormalizedDocument,
    progress: _WriteProgress,
) -> None:
    """Attempt each independent memory boundary and collect its durable receipt."""
    result = progress.result
    record = _record(normalized.summary, "summary", context)
    result["summary_memory_id"] = _write_component(context, progress, record, "summary")
    for index, memory in enumerate(normalized.section_memories):
        record = _record(memory.content, "section", context)
        memory_id = _write_component(context, progress, record, f"section:{index}")
        if memory_id is not None:
            result["section_memory_ids"].append(memory_id)
