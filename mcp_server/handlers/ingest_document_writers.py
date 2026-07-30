"""Memory writers + idempotency helpers for ``ingest_document``.

Split from the handler so each stays under the repo's size caps (CLAUDE.md:
300 lines/file, 40 lines/method) and the store-facing logic is unit-testable
with a fake store (mirrors ``ingest_docs_content_writers``). Provenance is
stamped on EVERY produced memory (issue #192): the version-scoped dedup tag
(idempotent re-ingest) plus the version-independent source tag (all versions
of one document stay recall-linkable).
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from mcp_server.core.document_model import (
    DocumentProvenance,
    document_provenance_dedup_tag,
    document_provenance_source_tag,
)
from mcp_server.core.document_normalizer import NormalizedDocument
from mcp_server.observability import silent_failure

logger = logging.getLogger(__name__)


def content_version(raw: str) -> str:
    """Stable version token for a document's bytes: a truncated SHA-256 of
    its text. Identical content → identical version → idempotent re-ingest
    (§13.1-A6); any edit changes the hash and triggers a fresh ingest.
    source: hashlib.sha256 (stdlib); 16 hex chars = 64 bits, ample to avoid
    accidental collision across one user's document set.

    §12 note: the ``"utf-8"`` → ``"UTF-8"`` mutant is EQUIVALENT — Python codec
    names are case-insensitive, so both select the identical codec."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _memory_tags(mem: dict) -> list:
    # §12 note: mutating the ``get`` default ([] → None/absent) is EQUIVALENT —
    # the isinstance guard maps any non-list (including None) back to [], so a
    # tagless mem yields [] regardless of the default.
    raw = mem.get("tags", [])
    return raw if isinstance(raw, list) else []


def already_ingested(store: Any, prov: DocumentProvenance) -> int | None:
    """Return the summary-memory id from a prior ingest of this exact
    ``(source, version)``, or None.

    Postcondition: never raises. A store without ``get_memories_by_tag``
    (e.g. the SQLite fallback) degrades to None ("always re-ingest") rather
    than erroring — the same tag-query limitation ``ingest_docs_content``
    already documents, not one this handler introduces."""
    tag = document_provenance_dedup_tag(prov)
    try:
        mems = store.get_memories_by_tag(tag, limit=5)
    except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
        silent_failure.note("ingest_document.already_ingested", exc)
        return None
    for mem in mems:
        if tag in _memory_tags(mem):
            return mem.get("id")
    return None


def _provenance_tags(prov: DocumentProvenance, extra: list[str]) -> list[str]:
    return [
        "document",
        "ingest",
        prov.source_kind,
        document_provenance_dedup_tag(prov),
        document_provenance_source_tag(prov),
        *extra,
    ]


def write_document_memories(
    store: Any,
    normalized: NormalizedDocument,
    prov: DocumentProvenance,
    domain: str,
    directory_context: str,
) -> dict[str, Any]:
    """Persist the summary memory + one memory per non-empty section.

    Precondition:  the caller has already confirmed this (source, version)
                   was not previously ingested (``already_ingested`` is None).
    Postcondition: writes exactly one protected summary memory and one
                   memory per ``normalized.section_memories`` entry, each
                   carrying the provenance tags (dedup + source + kind).
                   Returns ``{summary_memory_id, section_memory_ids}``. A
                   failed individual insert is logged and skipped, never
                   silently swallowed without a signal."""
    summary_record = {
        "content": normalized.summary,
        "tags": _provenance_tags(prov, ["summary"]),
        "source": f"ingest_document:{prov.source}",
        "domain": domain,
        "directory_context": directory_context,
        "importance": 0.8,
        "heat": 0.9,
        "confidence": 0.9,
        "is_protected": True,
        # M-D2 (7.4): bulk document-ingestion bookkeeping, not authored prose.
        "write_class": "mechanical",
    }
    summary_id: int | None = None
    try:
        summary_id = store.insert_memory(summary_record)
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.warning("ingest_document summary insert failed: %s", exc)

    section_ids: list[int] = []
    for mem in normalized.section_memories:
        record = {
            "content": mem.content,
            "tags": _provenance_tags(prov, ["section"]),
            "source": f"ingest_document:{prov.source}",
            "domain": domain,
            "directory_context": directory_context,
            "importance": 0.5,
            "heat": 0.6,
            "confidence": 0.9,
            "is_protected": False,
            "write_class": "mechanical",
        }
        try:
            section_ids.append(store.insert_memory(record))
        except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
            logger.warning(
                "ingest_document section insert failed (%s): %s", mem.heading, exc
            )

    return {"summary_memory_id": summary_id, "section_memory_ids": section_ids}
