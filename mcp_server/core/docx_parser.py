"""Pure docx (OOXML WordprocessingML) parser — string in, typed model out.

source: ADR-0163"""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from mcp_server.core.document_model import (
    DocumentAttachment,
    DocumentParseError,
    DocumentSection,
    DocumentTable,
    ParsedDocument,
    drop_empty_preamble,
)

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
# source: ECMA-376 Part 1 §22.8 — the relationships namespace of r:embed / r:id.
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_HEADING_RE = re.compile(r"^Heading\s*([1-9])$", re.IGNORECASE)


def _local(tag: str) -> str:
    """Strip the ``{namespace}`` prefix ElementTree prepends to qualified
    tags, leaving the bare local name (``p``, ``tbl``, ``t``, ...)."""
    # source: ADR-0163

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
    # source: ADR-0163

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


def _image_reference(image: ET.Element) -> str:
    """The relationship id of the picture itself: ``a:blip@r:embed`` for a
    ``w:drawing``, ``v:imagedata@r:id`` for a legacy ``w:pict``, else ``""``.

    Only those two elements name the image part; other descendants carry
    relationship ids too (``a:hlinkClick@r:id`` in ``wp:docPr`` is the
    picture's hyperlink and precedes the blip), so they are never read.

    source: ECMA-376 Part 1 §20.1.8.13 (blip), §14.1.2.11 (imagedata); issue #732
    """
    for node in image.iter():
        name = _local(node.tag)
        if name == "blip":
            return node.get(f"{{{_R_NS}}}embed", "")
        if name == "imagedata":
            return node.get(f"{{{_R_NS}}}id", "")
    return ""


def _collect_images(
    elem: ET.Element, section_index: int, out: list[DocumentAttachment]
) -> None:
    """Append every embedded image (``w:drawing`` + legacy ``w:pict``) under
    ``elem`` to ``out``, in document order, tagged with the index of its section.

    source: ADR-0163 (issue #732)
    """
    for node in elem.iter():
        if _local(node.tag) in ("drawing", "pict"):
            out.append(
                DocumentAttachment(
                    ordinal=len(out) + 1,
                    reference=_image_reference(node),
                    section_index=section_index,
                )
            )


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
                   section. ``attachments`` lists every embedded image in
                   document order (state ``unsupported``: never extracted).
                   An empty document yields a single empty preamble
                   section (``.is_empty()`` True).
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
    attachments: list[DocumentAttachment] = []

    for child in body:
        name = _local(child.tag)
        if name == "p":
            level = _heading_level(child)
            text = _paragraph_text(child)
            if level == 0:
                # source: ADR-0163

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
        _collect_images(child, len(sections) - 1, attachments)

    sections, attachments = drop_empty_preamble(sections, attachments)

    return ParsedDocument(
        title=resolved_title or "Untitled document",
        sections=sections,
        attachments=attachments,
    )
