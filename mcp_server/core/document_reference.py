"""Recall-side document reference: which source and version a hit came from.

source: issue #713 (slice 2); ADR-0161 (document provenance tags).

ingest_document tags every summary/section memory with
``doc-ingest:<kind>:<source>@<version>`` (``document_provenance_dedup_tag``).
Until now a caller had to parse that tag itself to learn which file and which
version a recalled segment belongs to. This module turns the tag into a typed
``document_sources`` field on the recall hit. Pure: no I/O, reads only the
hit's own tags.
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
        provs = document_provenances(mem.get("tags") or [])
        if provs:
            mem["document_sources"] = [
                {"source": p.source, "version": p.version, "source_kind": p.source_kind}
                for p in provs
            ]
