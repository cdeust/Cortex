"""Pure Confluence storage-format (XHTML) parser — string in, typed model out.

source: ADR-0135"""

from __future__ import annotations

import html.entities
import re
from xml.etree import ElementTree as ET

from mcp_server.core.document_images import ImageMarkup, collect_images
from mcp_server.core.document_model import (
    DocumentAttachment,
    DocumentParseError,
    DocumentSection,
    DocumentTable,
    ParsedDocument,
    drop_empty_preamble,
)

_XML_BUILTIN_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}
_ENTITY_RE = re.compile(r"&([a-zA-Z][a-zA-Z0-9]*);")
_HEADING_RE = re.compile(r"^h([1-6])$")
# source: ADR-0135


_WRAP_OPEN = '<_root xmlns:ac="urn:ac" xmlns:ri="urn:ri">'
_WRAP_CLOSE = "</_root>"


def _resolve_entities(xhtml: str) -> str:
    """Replace named HTML entities with their unicode char, leaving the five XML
    built-ins and numeric refs (``&#..;``) for the XML parser.

    source: ADR-0135
    """

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in _XML_BUILTIN_ENTITIES:
            return match.group(0)
        char = html.entities.html5.get(name + ";")
        return char if char is not None else match.group(0)

    return _ENTITY_RE.sub(_sub, xhtml)


def _local(tag: str) -> str:
    # source: ADR-0135

    return tag.rsplit("}", 1)[-1]


def _text_of(elem: ET.Element) -> str:
    """All descendant text of an element, whitespace-collapsed."""
    return re.sub(r"\s+", " ", "".join(elem.itertext())).strip()


def _table_of(table: ET.Element) -> DocumentTable:
    rows: list[list[str]] = []
    for tr in table.iter():
        if _local(tr.tag) != "tr":
            continue
        cells = [_text_of(cell) for cell in tr if _local(cell.tag) in ("th", "td")]
        if cells:
            rows.append(cells)
    return DocumentTable(rows=rows)


# source: Confluence storage format — an <ac:image> holds a ri:attachment
# (ri:filename) or ri:url (ri:value) naming the image; an XHTML <img> names it
# by src, inside or outside an <ac:image>. The ri: prefix is bound to urn:ri
# by _WRAP_OPEN.
_CONFLUENCE_IMAGES = ImageMarkup(
    containers=frozenset({"image"}),
    leaves={
        "attachment": "{urn:ri}filename",
        "url": "{urn:ri}value",
        "img": "src",
    },
    standalone=frozenset({"img"}),
)


def parse_confluence_storage(xhtml: str, *, title: str = "") -> ParsedDocument:
    """Parse Confluence storage-format XHTML into a :class:`ParsedDocument`.

    Precondition:  ``xhtml`` is a storage-format fragment (well-formed XML
                   modulo the ac:/ri: prefixes and named HTML entities this
                   function pre-resolves). ``title`` overrides the derived
                   title (else the first heading text, else ``"Untitled
                   page"``).
    Postcondition: returns a :class:`ParsedDocument` in document order —
                   ``<h1>``..``<h6>`` open sections, ``<p>`` bodies and
                   ``<table>``s attach to the current section, and text
                   before the first heading is a level-0 preamble.
                   ``attachments`` lists every ``<ac:image>``/``<img>``
                   in document order (state ``unsupported``). An empty
                   fragment yields an empty document.
    Raises:        :class:`DocumentParseError` on malformed XHTML — loud, so
                   the caller writes nothing.
    """
    resolved = _resolve_entities(xhtml)
    try:
        root = ET.fromstring(f"{_WRAP_OPEN}{resolved}{_WRAP_CLOSE}")
    except ET.ParseError as exc:
        raise DocumentParseError(f"malformed Confluence XHTML: {exc}") from exc

    preamble = DocumentSection(heading="", level=0)
    sections: list[DocumentSection] = [preamble]
    current = preamble
    resolved_title = title.strip()
    attachments: list[DocumentAttachment] = []

    for node in root:
        name = _local(node.tag)
        heading_match = _HEADING_RE.match(name)
        if heading_match:
            text = _text_of(node)
            level = int(heading_match.group(1))
            if not resolved_title and text:
                resolved_title = text
            current = DocumentSection(heading=text, level=level)
            sections.append(current)
        elif name == "table":
            current.tables.append(_table_of(node))
        else:
            text = _text_of(node)
            if text:
                current.body = f"{current.body}\n{text}".strip()
        collect_images(node, len(sections) - 1, _CONFLUENCE_IMAGES, attachments)

    sections, attachments = drop_empty_preamble(sections, attachments)

    return ParsedDocument(
        title=resolved_title or "Untitled page",
        sections=sections,
        attachments=attachments,
    )
