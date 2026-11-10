"""Name the bytes behind each embedded docx image (issue #732, slice 2).

Composition of the pure relationship parser (``core.docx_relationships``)
and the zip reader (``infrastructure.docx_media_reader``): each attachment
whose relationship id resolves to a package part gets that part's name,
SHA-256 digest and size. The bytes are identified, not preserved: ``state``
stays ``unsupported`` until a later slice stores them.

source: issue #732
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from mcp_server.core.document_model import DocumentAttachment
from mcp_server.core.docx_relationships import parse_docx_relationships
from mcp_server.infrastructure.docx_media_reader import (
    digest_docx_parts,
    read_docx_relationships_xml,
)


def identify_docx_images(
    path: Path, attachments: list[DocumentAttachment]
) -> list[DocumentAttachment]:
    """Return ``attachments`` with ``part``/``digest``/``size`` filled where
    the reference resolves to a member of the package at ``path``.

    Postcondition: same length and order; an attachment with no reference, a
                   linked (external) target or a part absent from the zip is
                   returned unchanged. The container is not opened when no
                   attachment carries a reference.
    Raises:        ``DocumentReadError`` (container) or ``DocumentParseError``
                   (relationships XML), before any write, like the main part.

    source: issue #732
    """
    if not any(a.reference for a in attachments):
        return attachments
    parts = parse_docx_relationships(read_docx_relationships_xml(path))
    wanted = {parts[a.reference] for a in attachments if a.reference in parts}
    digests = digest_docx_parts(path, wanted)
    identified: list[DocumentAttachment] = []
    for attachment in attachments:
        part = parts.get(attachment.reference, "")
        if part in digests:
            digest, size = digests[part]
            attachment = replace(attachment, part=part, digest=digest, size=size)
        identified.append(attachment)
    return identified
