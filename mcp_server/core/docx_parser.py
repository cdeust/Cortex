"""Pure docx (OOXML WordprocessingML) parser — string in, typed model out.

Zero I/O: this module is handed the already-unzipped ``word/document.xml``
string (the zip unpacking is infrastructure — ``infrastructure.document_
reader``) and turns it into a :class:`ParsedDocument`. Stdlib only
(``xml.etree.ElementTree`` parses an in-memory string — pure computation,
not I/O), so no heavyweight dependency (python-docx) is pulled in — issue
#192 §8: "Pure-Python parsing (zipfile + XML — no new heavyweight
dependency)."

WordprocessingML shape actually parsed (source: ECMA-376 Part 1, §17
"WordprocessingML", the OOXML spec; namespace ``w`` =
http://schemas.openxmlformats.org/wordprocessingml/2006/main):
  - ``w:body`` holds block-level children in document order: ``w:p``
    (paragraphs) and ``w:tbl`` (tables).
  - A paragraph's style is ``w:p/w:pPr/w:pStyle@w:val``; the built-in
    heading styles are ``Heading1``..``Heading9`` and ``Title`` (§17.7.4).
  - Text lives in ``w:t`` runs; ``w:tab`` / ``w:br`` are whitespace.
  - Embedded images appear as ``w:drawing`` (DrawingML, §20.4) or the
    legacy ``w:pict`` (VML) — counted, never extracted (issue #192
    non-goal: no image ingestion).
"""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from mcp_server.core.document_model import (
    DocumentParseError,
    DocumentSection,
    DocumentTable,
    ParsedDocument,
)

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_HEADING_RE = re.compile(r"^Heading\s*([1-9])$", re.IGNORECASE)


def _local(tag: str) -> str:
    """Strip the ``{namespace}`` prefix ElementTree prepends to qualified
    tags, leaving the bare local name (``p``, ``tbl``, ``t``, ...)."""
    # §12 note: several mutants here are EQUIVALENT because the input domain is
    # fixed — ElementTree tags for OOXML are always the single-'}' form
    # ``{uri}local`` (namespace URIs never contain '}'). So split==rsplit,
    # maxsplit 1==2==unbounded, and the result list always has exactly two
    # elements, making [-1]==[1]. None of those variants change the output.
    return tag.rsplit("}", 1)[-1]


def _paragraph_text(para: ET.Element) -> str:
    """Concatenate all run text in a paragraph, mapping tabs to a space and
    line breaks to a newline (WordprocessingML §17.3.3.31 tab / §17.3.3.1
    br). Empty runs contribute nothing."""
    parts: list[str] = []
    for node in para.iter():
        name = _local(node.tag)
        if name == "t":
            parts.append(node.text or "")
        elif name == "tab":
            parts.append(" ")
        elif name == "br":
            parts.append("\n")
    return "".join(parts).strip()


def _heading_level(para: ET.Element) -> int | None:
    """Return the heading level of a paragraph (1..9), 0 for ``Title``, or
    None if the paragraph is body text. Reads ``w:pPr/w:pStyle@w:val``."""
    style = para.find(f"{{{_W_NS}}}pPr/{{{_W_NS}}}pStyle")
    if style is None:
        return None
    # §12 note: the ``or ""`` → ``or "XXXX"`` mutant is EQUIVALENT — when a
    # pStyle carries no w:val, both the empty string and the sentinel fail the
    # ``title``/Heading regex below, so both fall through to "body text" (None).
    val = style.get(f"{{{_W_NS}}}val") or ""
    if val.lower() == "title":
        return 0
    match = _HEADING_RE.match(val.strip())
    return int(match.group(1)) if match else None


def _table_rows(tbl: ET.Element) -> DocumentTable:
    """Extract a ``w:tbl`` into a :class:`DocumentTable` of cell strings."""
    rows: list[list[str]] = []
    for tr in tbl.findall(f"{{{_W_NS}}}tr"):
        cells: list[str] = []
        for tc in tr.findall(f"{{{_W_NS}}}tc"):
            cell_text = " ".join(
                _paragraph_text(p)
                for p in tc.findall(f"{{{_W_NS}}}p")
                if _paragraph_text(p)
            )
            cells.append(cell_text)
        if cells:
            rows.append(cells)
    return DocumentTable(rows=rows)


def _count_images(root: ET.Element) -> int:
    """Count embedded images (``w:drawing`` + legacy ``w:pict``) in the
    whole document — these are skipped, not ingested (issue #192)."""
    return sum(1 for node in root.iter() if _local(node.tag) in ("drawing", "pict"))


def parse_docx_xml(document_xml: str, *, title: str = "") -> ParsedDocument:
    """Parse ``word/document.xml`` content into a :class:`ParsedDocument`.

    Precondition:  ``document_xml`` is the raw text of a docx's
                   ``word/document.xml`` (well-formed OOXML). ``title`` is an
                   optional override (else the first ``Title``/``Heading1``
                   text, else ``"Untitled document"``).
    Postcondition: returns a :class:`ParsedDocument` whose sections preserve
                   document order; heading paragraphs open new sections and
                   body paragraphs/tables attach to the current one. Text
                   before the first heading becomes a level-0 preamble
                   section. ``image_count`` reflects every embedded image
                   (skipped, never extracted). An empty document yields a
                   single empty preamble section (``.is_empty()`` True).
    Raises:        :class:`DocumentParseError` on malformed XML — loud, so
                   the caller writes nothing (no partial silent ingest).
    """
    try:
        root = ET.fromstring(document_xml)
    except ET.ParseError as exc:
        raise DocumentParseError(f"malformed docx XML: {exc}") from exc

    body = root.find(f"{{{_W_NS}}}body")
    if body is None:
        raise DocumentParseError("docx document.xml has no <w:body>")

    preamble = DocumentSection(heading="", level=0)
    sections: list[DocumentSection] = [preamble]
    current = preamble
    resolved_title = title.strip()

    for child in body:
        name = _local(child.tag)
        if name == "p":
            level = _heading_level(child)
            text = _paragraph_text(child)
            if level == 0:
                # ``Title`` style names the document; it is not a section
                # heading (that would duplicate the page's own title). Text
                # continues under the current section.
                if not resolved_title and text:
                    resolved_title = text
            elif level is not None:
                if not resolved_title and level == 1 and text:
                    resolved_title = text
                current = DocumentSection(heading=text, level=level)
                sections.append(current)
            elif text:
                current.body = f"{current.body}\n{text}".strip()
        elif name == "tbl":
            current.tables.append(_table_rows(child))

    if not preamble.body.strip() and not preamble.tables and len(sections) > 1:
        sections.remove(preamble)

    return ParsedDocument(
        title=resolved_title or "Untitled document",
        sections=sections,
        image_count=_count_images(root),
    )
