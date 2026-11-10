"""The docx relationships part is read, and media parts are digested (#732).

source: issue #732
"""

from __future__ import annotations

import hashlib
import zipfile

import pytest

from mcp_server.infrastructure.document_reader import DocumentReadError
from mcp_server.infrastructure.docx_media_reader import (
    digest_docx_parts,
    read_docx_relationships_xml,
)

_RELS = "word/_rels/document.xml.rels"


def _zip(path, members: dict[str, bytes]):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return path


def test_the_relationships_part_is_returned_as_text(tmp_path):
    p = _zip(tmp_path / "a.docx", {_RELS: "<Relationships/>".encode()})
    assert read_docx_relationships_xml(p) == "<Relationships/>"


def test_a_package_without_relationships_part_has_none(tmp_path):
    p = _zip(tmp_path / "a.docx", {"word/document.xml": b"<w/>"})
    assert read_docx_relationships_xml(p) == ""


def test_an_oversized_relationships_part_is_refused(tmp_path):
    p = _zip(tmp_path / "a.docx", {_RELS: b"x" * 11})
    with pytest.raises(DocumentReadError, match="exceeds 10-byte cap"):
        read_docx_relationships_xml(p, max_bytes=10)


def test_a_relationships_part_at_the_cap_is_read(tmp_path):
    p = _zip(tmp_path / "a.docx", {_RELS: b"x" * 10})
    assert read_docx_relationships_xml(p, max_bytes=10) == "x" * 10


def test_undecodable_relationships_bytes_are_refused(tmp_path):
    p = _zip(tmp_path / "a.docx", {_RELS: b"\xff\xfe"})
    with pytest.raises(DocumentReadError, match="not valid UTF-8"):
        read_docx_relationships_xml(p)


@pytest.mark.parametrize("reader", [read_docx_relationships_xml, digest_docx_parts])
def test_a_missing_or_corrupt_container_is_refused(tmp_path, reader):
    args = () if reader is read_docx_relationships_xml else ([],)
    with pytest.raises(DocumentReadError, match="not found"):
        reader(tmp_path / "absent.docx", *args)
    (tmp_path / "bad.docx").write_bytes(b"not a zip")
    with pytest.raises(DocumentReadError, match="cannot open"):
        reader(tmp_path / "bad.docx", *args)


def test_each_present_part_is_digested_and_absent_ones_left_out(tmp_path):
    image = bytes(range(256)) * 600  # larger than one 64 KiB read
    p = _zip(tmp_path / "a.docx", {"word/media/i.png": image, "word/media/j.png": b""})
    out = digest_docx_parts(p, ["word/media/i.png", "word/media/j.png", "word/x"])
    assert out == {
        "word/media/i.png": (f"sha256:{hashlib.sha256(image).hexdigest()}", len(image)),
        "word/media/j.png": (f"sha256:{hashlib.sha256(b'').hexdigest()}", 0),
    }


def test_a_member_whose_crc_fails_is_refused(tmp_path):
    p = tmp_path / "a.docx"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_STORED) as z:
        z.writestr("word/media/i.png", b"A" * 64)
    raw = bytearray(p.read_bytes())
    at = raw.index(b"word/media/i.png") + len("word/media/i.png")
    raw[at] ^= 0xFF  # first stored data byte, after the local header's name
    p.write_bytes(bytes(raw))
    with pytest.raises(DocumentReadError, match="cannot read word/media/i.png"):
        digest_docx_parts(p, ["word/media/i.png"])
