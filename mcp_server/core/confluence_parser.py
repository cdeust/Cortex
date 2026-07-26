"""Pure Confluence storage-format (XHTML) parser — string in, typed model out.

Zero I/O: handed the storage-format XHTML string (export ingestion reads it
off disk in infrastructure; the live REST connector — enterprise-backlog#28,
OUT of scope here — will fetch the identical string over REST and call THIS
function), it produces a :class:`ParsedDocument` — the same shape the docx
adapter produces, so both feed one normalization seam.

Storage format shape parsed (source: Atlassian "Confluence Storage Format"
reference — confluence.atlassian.com/doc/confluence-storage-format-790796544.html):
  - Headings are ``<h1>``..``<h6>``; body text is ``<p>``.
  - Tables are ``<table>`` with ``<tr>`` rows and ``<th>``/``<td>`` cells.
  - Images are the ``<ac:image>`` macro or plain ``<img>`` — counted, never
    extracted (issue #192 non-goal).

Storage format is well-formed XML but uses the Confluence ``ac:``/``ri:``
namespace prefixes (undeclared in the fragment) and named HTML entities
(``&nbsp;`` etc.) that bare XML does not define. Both are pre-resolved here
(entities via the stdlib ``html.entities.html5`` table; namespaces via a
declaring wrapper) so a genuine structural defect — an unclosed tag — still
raises loudly rather than being masked.
"""

from __future__ import annotations

import html.entities
import re
from xml.etree import ElementTree as ET

from mcp_server.core.document_model import (
    DocumentParseError,
    DocumentSection,
    DocumentTable,
    ParsedDocument,
)

_XML_BUILTIN_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}
_ENTITY_RE = re.compile(r"&([a-zA-Z][a-zA-Z0-9]*);")
_HEADING_RE = re.compile(r"^h([1-6])$")
# Wrapper declaring the storage-format namespaces so ElementTree accepts the
# ac:/ri: prefixes. source: Atlassian storage-format reference (ac = macro
# namespace, ri = resource-identifier namespace).
_WRAP_OPEN = '<_root xmlns:ac="urn:ac" xmlns:ri="urn:ri">'
_WRAP_CLOSE = "</_root>"


def _resolve_entities(xhtml: str) -> str:
    """Replace named HTML entities with their unicode char, leaving the five
    XML built-ins and numeric refs (``&#..;``) for the XML parser. An unknown
    name is left intact so the parser fails loudly on genuinely broken input."""

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in _XML_BUILTIN_ENTITIES:
            return match.group(0)
        char = html.entities.html5.get(name + ";")
        return char if char is not None else match.group(0)

    return _ENTITY_RE.sub(_sub, xhtml)


def _local(tag: str) -> str:
    # §12 note: split-vs-rsplit / maxsplit / index mutants are EQUIVALENT here
    # — an ElementTree tag is always the single-'}' form ``{uri}local``, so all
    # those variants return the same local name (see docx_parser._local).
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


def _count_images(root: ET.Element) -> int:
    return sum(1 for node in root.iter() if _local(node.tag) in ("image", "img"))


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
                   ``image_count`` counts every ``<ac:image>``/``<img>``
                   (skipped). An empty fragment yields an empty document.
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

    if not preamble.body.strip() and not preamble.tables and len(sections) > 1:
        sections.remove(preamble)

    return ParsedDocument(
        title=resolved_title or "Untitled page",
        sections=sections,
        image_count=_count_images(root),
    )
