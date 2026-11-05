"""Typed model for ingested documents — the shared normalization seam.

source: ADR-0161"""

from __future__ import annotations

from dataclasses import dataclass, field


class DocumentParseError(Exception):
    """Raised when a document's markup is malformed and cannot be parsed.

    source: ADR-0161"""


@dataclass(frozen=True)
class DocumentTable:
    """A table extracted from a document: a list of rows, each a list of cell strings.

    source: ADR-0161
    """

    rows: list[list[str]]


@dataclass
class DocumentSection:
    """One heading-delimited section of a document.

    source: ADR-0161"""

    heading: str
    level: int
    body: str = ""
    tables: list[DocumentTable] = field(default_factory=list)


def document_section_is_empty(section: "DocumentSection") -> bool:
    """True when the section carries no body text and no tables — a headings-only
    section.

    source: ADR-0161
    """
    return not section.body.strip() and not section.tables


@dataclass
class ParsedDocument:
    """The normalized shape every adapter produces.

    source: ADR-0161"""

    title: str
    sections: list[DocumentSection] = field(default_factory=list)
    image_count: int = 0


def parsed_document_is_empty(doc: "ParsedDocument") -> bool:
    """True when the document yielded no text and no tables at all.

    source: ADR-0161

        A free function, not a method — see `document_section_is_empty`.
    """
    return all(document_section_is_empty(s) for s in doc.sections)


@dataclass(frozen=True)
class DocumentProvenance:
    """Where an ingested document came from and which version was ingested.

    source: ADR-0161"""

    source: str
    version: str
    source_kind: str


def document_provenance_dedup_tag(prov: "DocumentProvenance") -> str:
    """Canonical idempotency key: one document source at one version.

    source: ADR-0161

    A free function, not a method — see `document_section_is_empty`.
    """
    return f"doc-ingest:{prov.source_kind}:{prov.source}@{prov.version}"


def document_provenance_source_tag(prov: "DocumentProvenance") -> str:
    """Version-independent tag anchoring every memory to this source.

    source: ADR-0161
    """
    return f"doc-src:{prov.source_kind}:{prov.source}"


_DEDUP_TAG_PREFIX = "doc-ingest:"


def parse_document_provenance_dedup_tag(tag: str) -> "DocumentProvenance | None":
    """Inverse of ``document_provenance_dedup_tag``; None for any other tag.

    source: issue #713 (slice 2); ADR-0161

    The kind never holds ':' (see ``ingest_document._resolve_format``), so the
    first ':' after the prefix ends it; the version is a hex digest, so the
    last '@' starts it.
    A source path may hold either character (``C:\\a@b.docx``).
    """
    if not tag.startswith(_DEDUP_TAG_PREFIX):
        return None
    kind, sep, rest = tag[len(_DEDUP_TAG_PREFIX) :].partition(":")
    source, at, version = rest.rpartition("@")
    if not (kind and sep and source and at and version):
        return None
    return DocumentProvenance(source=source, version=version, source_kind=kind)
