"""identify_docx_images names the bytes behind each docx image (#732).

source: issue #732
"""

from __future__ import annotations

import hashlib
import zipfile

import pytest

from mcp_server.core.document_model import DocumentAttachment, DocumentParseError
from mcp_server.handlers.ingest_document_media import identify_docx_images
from mcp_server.infrastructure.document_reader import DocumentReadError

_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
_RELS = "word/_rels/document.xml.rels"


def _docx(path, rels: str, media: dict[str, bytes]):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", "<w/>")
        z.writestr(_RELS, rels)
        for name, data in media.items():
            z.writestr(name, data)
    return path


def _rel(rid: str, target: str) -> str:
    return f'<Relationship Id="{rid}" Type="t" Target="{target}"/>'


def test_without_a_reference_the_container_is_not_opened(tmp_path):
    attachments = [DocumentAttachment(ordinal=1, reference="", section_index=0)]
    out = identify_docx_images(tmp_path / "absent.docx", attachments)
    assert out is attachments


def test_each_resolved_reference_gets_its_part_digest_and_size(tmp_path):
    png = b"\x89PNG" + b"\x01" * 50
    body = _rel("a", "media/i.png") + _rel("b", "media/gone.png")
    rels = f'<Relationships xmlns="{_PKG}">{body}</Relationships>'
    p = _docx(tmp_path / "d.docx", rels, {"word/media/i.png": png})
    attachments = [
        DocumentAttachment(ordinal=1, reference="a", section_index=0),
        DocumentAttachment(ordinal=2, reference="b", section_index=1),
        DocumentAttachment(ordinal=3, reference="", section_index=1),
        DocumentAttachment(ordinal=4, reference="a", section_index=2),
    ]
    out = identify_docx_images(p, attachments)
    digest = f"sha256:{hashlib.sha256(png).hexdigest()}"
    assert [(a.ordinal, a.part, a.digest, a.size) for a in out] == [
        (1, "word/media/i.png", digest, len(png)),
        (2, "", "", None),
        (3, "", "", None),
        (4, "word/media/i.png", digest, len(png)),
    ]
    assert [a.section_index for a in out] == [0, 1, 1, 2]
    assert {a.state for a in out} == {"unsupported"}


def test_malformed_relationships_raise_before_any_digest(tmp_path):
    p = _docx(tmp_path / "d.docx", "<Rel", {})
    attachments = [DocumentAttachment(ordinal=1, reference="a", section_index=0)]
    with pytest.raises(DocumentParseError):
        identify_docx_images(p, attachments)


def test_an_unreadable_container_raises_a_read_error(tmp_path):
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"not a zip")
    attachments = [DocumentAttachment(ordinal=1, reference="a", section_index=0)]
    with pytest.raises(DocumentReadError):
        identify_docx_images(bad, attachments)
