"""Typed model for ingested documents — the shared normalization seam.

Pure core (zero I/O): every type here is a plain in-memory value object.
Both document adapters (docx via ``core.docx_parser``, Confluence storage
format via ``core.confluence_parser``) parse the bytes/strings they are
handed into a :class:`ParsedDocument`; :func:`core.document_normalizer`
turns that single shape into the wiki page + memory payloads the existing
``wiki_write``/``remember`` path already consumes.

This is the seam the live-Confluence REST connector (enterprise-backlog#28,
OUT of scope here) is built to reuse: that connector fetches storage-format
XHTML over REST and hands the string to ``confluence_parser`` →
``ParsedDocument`` → ``document_normalizer`` → the same write path, with a
:class:`DocumentProvenance` carrying the page URL + version instead of a
file path + content hash. No parsing/normalization logic is duplicated for
the live leg — only the byte-source (file read vs REST fetch) differs, and
that lives in infrastructure/handlers, never here.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class DocumentParseError(Exception):
    """Raised when a document's markup is malformed and cannot be parsed.

    A loud failure by design (issue #192 edge case: malformed XML must
    surface a hard error, never a partial silent write). The handler maps
    this to an ``{"ingested": false, ...}`` response BEFORE any wiki page or
    memory is written, so a malformed document leaves the store untouched.
    """


@dataclass(frozen=True)
class DocumentTable:
    """A table extracted from a document: a list of rows, each a list of
    cell strings. The header row (if any) is simply ``rows[0]`` — the model
    does not distinguish it, the renderer does."""

    rows: list[list[str]]


@dataclass
class DocumentSection:
    """One heading-delimited section of a document.

    ``level`` is the heading depth (0 = document preamble text that appears
    before the first heading; 1 = top-level heading, 2 = subheading, ...).
    ``body`` is the concatenated paragraph text under the heading (tables
    excluded — those are carried structurally in ``tables`` so the renderer
    can emit real markdown tables rather than flattened text)."""

    heading: str
    level: int
    body: str = ""
    tables: list[DocumentTable] = field(default_factory=list)


def document_section_is_empty(section: "DocumentSection") -> bool:
    """True when the section carries no body text and no tables — a
    headings-only section (issue #192 edge case). The renderer still
    emits the heading; the memory writer skips empty sections so a bare
    heading does not become a contentless memory.

    A free function, not a method: mutmut categorically excludes the body
    of any `@dataclass`-decorated class (`mutmut/mutation/file_mutation.py:
    236`), so logic placed on `DocumentSection` methods would carry zero
    mutation coverage no matter how the test loader names the module
    (issue #262 3rd pass; issue #282).
    """
    return not section.body.strip() and not section.tables


@dataclass
class ParsedDocument:
    """The normalized shape every adapter produces.

    ``image_count`` is the number of embedded images detected and
    deliberately NOT ingested (issue #192 non-goal: no OCR / no image
    extraction). It drives the explicit skip notice (F1) — a non-zero count
    is surfaced to the caller, never silently dropped.
    """

    title: str
    sections: list[DocumentSection] = field(default_factory=list)
    image_count: int = 0


def parsed_document_is_empty(doc: "ParsedDocument") -> bool:
    """True when the document yielded no text and no tables at all
    (issue #192 edge case: empty doc). Distinct from a malformed doc,
    which raises :class:`DocumentParseError` instead.

    A free function, not a method — see `document_section_is_empty`.
    """
    return all(document_section_is_empty(s) for s in doc.sections)


@dataclass(frozen=True)
class DocumentProvenance:
    """Where an ingested document came from and which version was ingested.

    ``source`` is a file path (export ingestion) or a page URL (the live
    REST connector, enterprise-backlog#28). ``version`` is a content hash
    for files (so re-ingesting an unchanged file is idempotent) or the
    Confluence page version number for the live leg. ``source_kind`` is one
    of ``"docx"`` / ``"confluence-export"`` / ``"confluence-api"`` — the
    tag prefix that lets ``recall``/staleness treat documents the way they
    treat code references."""

    source: str
    version: str
    source_kind: str


def document_provenance_dedup_tag(prov: "DocumentProvenance") -> str:
    """Canonical idempotency key: one document source at one version.

    A prior ingestion of the same ``(source, version)`` carries this
    exact tag; the handler checks for it and skips re-writing (§13.1-A6
    idempotent re-ingest). A NEW version produces a different tag, so an
    updated document is re-ingested rather than silently ignored.

    A free function, not a method — see `document_section_is_empty`.
    """
    return f"doc-ingest:{prov.source_kind}:{prov.source}@{prov.version}"


def document_provenance_source_tag(prov: "DocumentProvenance") -> str:
    """Version-independent tag anchoring every memory to this source, so
    all ingested versions of one document are recall-linkable."""
    return f"doc-src:{prov.source_kind}:{prov.source}"
