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
    with pytest.raises(DocumentReadError, match="cannot read word/media/i.png") as e:
        digest_docx_parts(p, ["word/media/i.png"])
    assert str(p) in str(e.value)  # the error names the docx it came from


def test_a_relationships_part_whose_crc_fails_is_refused(tmp_path):
    p = tmp_path / "a.docx"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_STORED) as z:
        z.writestr(_RELS, b"<Relationships/>")
    raw = bytearray(p.read_bytes())
    at = raw.index(_RELS.encode()) + len(_RELS)
    raw[at] ^= 0xFF  # first stored data byte, after the local header's name
    p.write_bytes(bytes(raw))
    with pytest.raises(DocumentReadError, match="cannot read word/_rels") as e:
        read_docx_relationships_xml(p)
    assert str(p) in str(e.value)


def _corrupt_deflate(path, name: str, data: bytes):
    """Write ``name`` deflated, then break its first compressed block."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(name, data)
    raw = bytearray(path.read_bytes())
    at = raw.index(name.encode()) + len(name)
    raw[at] = 0xFF  # BTYPE 11 (reserved): an invalid deflate block header
    path.write_bytes(bytes(raw))
    return path


@pytest.mark.parametrize(
    ("name", "read"),
    [
        ("word/media/i.png", lambda p: digest_docx_parts(p, ["word/media/i.png"])),
        (_RELS, read_docx_relationships_xml),
    ],
)
def test_a_member_with_a_corrupt_deflate_stream_is_refused(tmp_path, name, read):
    p = _corrupt_deflate(tmp_path / "a.docx", name, b"<Relationships/>" * 64)
    with pytest.raises(DocumentReadError, match=f"cannot read {name}"):
        read(p)


def test_a_part_is_read_in_bounded_chunks(tmp_path, monkeypatch):
    """Memory stays bounded: no read asks for the whole member at once."""
    image = b"x" * (3 * 65_536 + 1)
    p = _zip(tmp_path / "a.docx", {"word/media/i.png": image})
    sizes: list[int | None] = []
    real_read = zipfile.ZipExtFile.read

    def _read(self, n=-1):
        sizes.append(n)
        return real_read(self, n)

    monkeypatch.setattr(zipfile.ZipExtFile, "read", _read)
    out = digest_docx_parts(p, ["word/media/i.png"])
    assert out["word/media/i.png"][1] == len(image)
    assert sizes and all(n == 65_536 for n in sizes)
