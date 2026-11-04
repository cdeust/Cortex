"""Pure normalization seam: :class:`ParsedDocument` → wiki page + memory
payloads, stamped with provenance.

source: ADR-0162"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from mcp_server.core.document_model import (
    DocumentProvenance,
    DocumentSection,
    DocumentTable,
    ParsedDocument,
    document_section_is_empty,
    parsed_document_is_empty,
)

_MAX_SLUG = 80


@dataclass
class SectionMemory:
    """One memory payload derived from a non-empty document section."""

    heading: str
    content: str


@dataclass
class NormalizedDocument:
    """Everything the handler needs to persist one ingested document.

    source: ADR-0162"""

    wiki_rel_path: str
    wiki_markdown: str
    summary: str
    section_memories: list[SectionMemory] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    image_count: int = 0


def slugify(text: str) -> str:
    # source: ADR-0162

    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:_MAX_SLUG] or "document"


def _render_table(table: DocumentTable) -> str:
    """Render a :class:`DocumentTable` as a GitHub-flavoured markdown table.
    The first row is treated as the header (Confluence/docx both place header
    cells first); a single-row table still renders with an empty separator."""
    if not table.rows:
        return ""
    width = max(len(r) for r in table.rows)
    header = table.rows[0] + [""] * (width - len(table.rows[0]))
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    for row in table.rows[1:]:
        padded = row + [""] * (width - len(row))
        lines.append("| " + " | ".join(padded) + " |")
    return "\n".join(lines)


def _render_section(section: DocumentSection) -> str:
    parts: list[str] = []
    if section.heading:
        hashes = "#" * min(max(section.level, 1) + 1, 6)
        parts.append(f"{hashes} {section.heading}")
    if section.body.strip():
        parts.append(section.body.strip())
    for table in section.tables:
        rendered = _render_table(table)
        if rendered:
            parts.append(rendered)
    return "\n\n".join(parts)


def _push_heading(
    stack: list[tuple[int, str]], section: DocumentSection
) -> list[tuple[int, str]]:
    """Heading ancestry after ``section``: shallower-or-equal levels close.

    A preamble (no heading) leaves the ancestry untouched.
    source: issue #713 — repeated text under different parents must stay
    distinguishable.
    """
    if not section.heading:
        return stack
    kept = [(level, text) for level, text in stack if level < section.level]
    return [*kept, (section.level, section.heading)]


def _section_memory(
    section: DocumentSection, ancestry: list[tuple[int, str]]
) -> SectionMemory | None:
    """Memory payload labelled by the section's full heading path.

    source: issue #713"""
    if document_section_is_empty(section):
        return None
    body_parts = [section.body.strip()] if section.body.strip() else []
    for table in section.tables:
        rendered = _render_table(table)
        if rendered:
            body_parts.append(rendered)
    label = section.heading or "(document body)"
    path = " > ".join(text for _, text in ancestry) if section.heading else label
    return SectionMemory(
        heading=label, content=f"[{path}]\n\n" + "\n\n".join(body_parts)
    )


def _frontmatter(doc: ParsedDocument, prov: DocumentProvenance) -> list[str]:
    return [
        "---",
        f"title: {doc.title}",
        "kind: reference",
        f"tags: [document, ingest, {prov.source_kind}]",
        f"source: {prov.source}",
        f"source_kind: {prov.source_kind}",
        f"version: {prov.version}",
        "---",
        "",
        f"# {doc.title}",
        "",
        f"> Ingested from `{prov.source}` (version `{prov.version}`).",
        "",
    ]


def normalize_document(
    doc: ParsedDocument, prov: DocumentProvenance
) -> NormalizedDocument:
    """Turn a parsed document + its provenance into wiki + memory payloads.

    Precondition: ``doc`` is a parsed document; ``prov`` identifies its
    source and version.
    Postcondition: returns a NormalizedDocument carrying source and version
    on the wiki frontmatter and every memory; each section memory is
    labelled by its heading path (ancestors joined by " > "). Nonzero
    image_count produces
    a skipped-image notice. Empty documents yield a page, empty notice, and
    no section memories. Headings-only sections produce no memory.
    source: ADR-0162"""
    slug = slugify(doc.title)
    lines = _frontmatter(doc, prov)

    notices: list[str] = []
    if doc.image_count:
        notice = (
            f"{doc.image_count} embedded image(s) skipped — images are not "
            "ingested (issue #192 non-goal: no OCR/image extraction)."
        )
        notices.append(notice)
        lines.append(f"> Note: {notice}")
        lines.append("")
    if parsed_document_is_empty(doc):
        empty_notice = "Document contained no extractable text."
        notices.append(empty_notice)
        lines.append(f"> Note: {empty_notice}")
        lines.append("")

    section_memories: list[SectionMemory] = []
    ancestry: list[tuple[int, str]] = []
    for section in doc.sections:
        rendered = _render_section(section)
        if rendered:
            lines.append(rendered)
            lines.append("")
        ancestry = _push_heading(ancestry, section)
        mem = _section_memory(section, ancestry)
        if mem is not None:
            section_memories.append(mem)

    heading_names = [s.heading for s in doc.sections if s.heading]
    summary = (
        f"Document ingested: '{doc.title}' from {prov.source} "
        f"({len(section_memories)} sections, {doc.image_count} images skipped)."
    )
    if heading_names:
        summary += " Sections: " + ", ".join(heading_names[:8]) + "."

    return NormalizedDocument(
        wiki_rel_path=f"documents/{slug}.md",
        wiki_markdown="\n".join(lines).rstrip() + "\n",
        summary=summary,
        section_memories=section_memories,
        notices=notices,
        image_count=doc.image_count,
    )
