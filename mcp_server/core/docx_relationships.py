"""Pure parser of a docx main part's relationships (issue #732, slice 2).

An embedded image names its bytes by a relationship id (``a:blip@r:embed``,
``v:imagedata@r:id``). The id resolves, in ``word/_rels/document.xml.rels``,
to a target: a package part (``media/image1.png``) for an embedded image, or
an outside URI (``TargetMode="External"``) for a linked one. This module maps
each internal id to the package part name, the zip member that holds the
bytes; a linked image has no part in the package and is left out.

source: ECMA-376 Part 2 (Open Packaging Conventions) §9.3 (relationships
part, ``Id``/``Target``/``TargetMode``), Annex A.3 (resolving a relative
target against the source part's URI); issue #732
"""

from __future__ import annotations

from xml.etree import ElementTree as ET

from mcp_server.core.document_model import DocumentParseError

# source: ECMA-376 Part 2 §9.3.2 — the namespace of <Relationships>/<Relationship>.
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
# source: ECMA-376 Part 2 §9.3.2.2 — TargetMode is Internal unless it says External.
_EXTERNAL = "External"
# source: ECMA-376 Part 2 §9.3 — the main part ``/word/document.xml`` is the
# source part of ``word/_rels/document.xml.rels``; relative targets resolve
# against its directory.
_SOURCE_DIR = ("word",)


def _resolve_part(target: str) -> str:
    """Package part name (no leading ``/``) of a relationship target.

    Postcondition: an absolute target (``/word/media/a.png``) is taken from
    the package root; a relative one from ``word/``. ``.`` segments are
    dropped and ``..`` removes the previous segment, never above the root.
    Returns ``""`` when nothing names a part (empty target, or one that is
    only ``/``, ``.`` or ``..`` segments).

    source: ECMA-376 Part 2 Annex A.3; RFC 3986 §5.2.4 (dot segments)
    """
    named = [s for s in target.split("/") if s not in ("", ".")]
    if all(s == ".." for s in named):
        return ""
    segments: list[str] = [] if target.startswith("/") else list(_SOURCE_DIR)
    for segment in named:
        if segment != "..":
            segments.append(segment)
        elif segments:
            segments.pop()
    return "/".join(segments)


def parse_docx_relationships(rels_xml: str) -> dict[str, str]:
    """Map each internal relationship id of the main part to its part name.

    Precondition:  ``rels_xml`` is the text of ``word/_rels/document.xml.rels``
                   (``""`` when the package has none: no id resolves).
    Postcondition: ``{id: part}`` for every ``Relationship`` whose
                   ``TargetMode`` is not ``External`` and whose target names
                   a part; external and empty targets are absent.
    Raises:        :class:`DocumentParseError` on malformed XML, so a broken
                   package is reported, not read as one without images.

    source: ECMA-376 Part 2 §9.3; issue #732
    """
    if not rels_xml:
        return {}
    try:
        root = ET.fromstring(rels_xml)
    except ET.ParseError as exc:
        raise DocumentParseError(f"malformed docx relationships XML: {exc}") from exc
    parts: dict[str, str] = {}
    for rel in root.iter(f"{{{_PKG_REL_NS}}}Relationship"):
        rid = rel.get("Id", "")
        if not rid or rel.get("TargetMode") == _EXTERNAL:
            continue
        part = _resolve_part(rel.get("Target", ""))
        if part:
            parts[rid] = part
    return parts
