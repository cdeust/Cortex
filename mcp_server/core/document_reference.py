"""Recall-side document reference: which source and version a hit came from.

source: issue #713 (slices 2 and 3); ADR-0161 (document provenance tags).

ingest_document tags every summary/section memory with
``doc-ingest:<kind>:<source>@<version>`` (``document_provenance_dedup_tag``).
Until now a caller had to parse that tag itself to learn which file and which
version a recalled segment belongs to. This module turns the tag into a typed
``document_sources`` field on the recall hit. Pure: no I/O, reads only the
hit's own tags. Slice 3 applies the same reading to the memories a wiki page
cites, so a synthesis traces back to the segments and versions it rests on.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.document_model import (
    DocumentProvenance,
    parse_document_provenance_dedup_tag,
)


def document_provenances(tags: list[Any]) -> list[DocumentProvenance]:
    """Every distinct document provenance the tags name, in tag order."""
    found: list[DocumentProvenance] = []
    for tag in tags:
        prov = parse_document_provenance_dedup_tag(str(tag))
        if prov is not None and prov not in found:
            found.append(prov)
    return found


def annotate_document_sources(results: list[dict[str, Any]]) -> None:
    """Add ``document_sources`` to each hit written by ingest_document, in place.

    A hit with no ``doc-ingest:`` tag gets no key: it is not a document segment,
    and an empty list would read as "document with unknown source". The value is
    always a list, so a hit whose tags name two versions shows both instead of
    an arbitrary pick.
    """
    for mem in results:
        refs = _source_refs(mem.get("tags") or [])
        if refs:
            mem["document_sources"] = refs


def _source_refs(tags: list[Any]) -> list[dict[str, str]]:
    return [
        {"source": p.source, "version": p.version, "source_kind": p.source_kind}
        for p in document_provenances(tags)
    ]


def cited_memory_sources(
    cited_ids: list[int], memories_by_id: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    """One reference per cited memory id, in citation order.

    A memory the store still holds yields ``{"memory_id"}`` plus
    ``document_sources`` when it is a document segment (the same rule as a
    recall hit). An id the store no longer holds yields ``{"memory_id",
    "missing": True}``: the reference is kept and marked, never dropped or
    replaced by a guessed location.
    """
    refs: list[dict[str, Any]] = []
    for mid in cited_ids:
        mem = memories_by_id.get(mid)
        if mem is None:
            refs.append({"memory_id": mid, "missing": True})
            continue
        ref: dict[str, Any] = {"memory_id": mid}
        sources = _source_refs(mem.get("tags") or [])
        if sources:
            ref["document_sources"] = sources
        refs.append(ref)
    return refs
