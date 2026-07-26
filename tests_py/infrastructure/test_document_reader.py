"""Unit tests for the document reader infrastructure (issue #192)."""

from __future__ import annotations

import locale
import zipfile
from pathlib import Path

import pytest

from mcp_server.infrastructure.document_reader import (
    DocumentReadError,
    read_confluence_export,
    read_docx_xml,
)


def _make_docx(path: Path, xml: str = "<w:document/>") -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)
        z.writestr("[Content_Types].xml", "<Types/>")
    return path


class TestReadDocxXml:
    def test_reads_main_part(self, tmp_path: Path):
        p = _make_docx(tmp_path / "a.docx", "<w:document>hi</w:document>")
        assert read_docx_xml(p) == "<w:document>hi</w:document>"

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(DocumentReadError, match="not found"):
            read_docx_xml(tmp_path / "nope.docx")

    def test_non_zip_raises(self, tmp_path: Path):
        bad = tmp_path / "bad.docx"
        bad.write_bytes(b"this is not a zip")
        with pytest.raises(DocumentReadError, match="cannot open"):
            read_docx_xml(bad)

    def test_zip_without_main_part_raises(self, tmp_path: Path):
        p = tmp_path / "empty.docx"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("other.xml", "x")
        with pytest.raises(DocumentReadError, match="not a Word document"):
            read_docx_xml(p)

    def test_oversized_main_part_raises(self, tmp_path: Path):
        p = _make_docx(tmp_path / "big.docx", "x" * 20)
        with pytest.raises(DocumentReadError, match="exceeds"):
            read_docx_xml(p, max_bytes=10)

    def test_main_part_exactly_at_cap_is_read(self, tmp_path: Path):
        # Boundary: file_size == max_bytes must be accepted (strict '>').
        p = _make_docx(tmp_path / "exact.docx", "x" * 10)
        assert read_docx_xml(p, max_bytes=10) == "x" * 10

    def test_undecodable_main_part_raises(self, tmp_path: Path):
        p = tmp_path / "bad.docx"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("word/document.xml", b"\xff\xfe\x00\x01")
        with pytest.raises(DocumentReadError, match="not valid UTF-8"):
            read_docx_xml(p)


class TestReadConfluenceExport:
    def test_reads_text(self, tmp_path: Path):
        p = tmp_path / "page.xml"
        p.write_text("<h1>Hi</h1>", encoding="utf-8")
        assert read_confluence_export(p) == "<h1>Hi</h1>"

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(DocumentReadError, match="not found"):
            read_confluence_export(tmp_path / "nope.xml")

    def test_oversized_raises(self, tmp_path: Path):
        p = tmp_path / "big.xml"
        p.write_text("x" * 20, encoding="utf-8")
        with pytest.raises(DocumentReadError, match="exceeds"):
            read_confluence_export(p, max_bytes=10)

    def test_undecodable_bytes_raise(self, tmp_path: Path):
        p = tmp_path / "bad.xml"
        p.write_bytes(b"\xff\xfe\x00\x01")
        with pytest.raises(DocumentReadError, match="not valid UTF-8"):
            read_confluence_export(p)

    def test_exactly_at_cap_is_read(self, tmp_path: Path):
        p = tmp_path / "exact.xml"
        p.write_text("x" * 10, encoding="utf-8")
        assert read_confluence_export(p, max_bytes=10) == "x" * 10

    def test_decodes_utf8_regardless_of_platform_locale(
        self, tmp_path: Path, monkeypatch
    ):
        # The read must be UTF-8, not the platform-default encoding: force a
        # non-UTF-8 preferred encoding and confirm a multibyte char round-trips.
        monkeypatch.setattr(locale, "getpreferredencoding", lambda *a: "latin-1")
        p = tmp_path / "u.xml"
        p.write_bytes("café".encode("utf-8"))
        assert read_confluence_export(p) == "café"

    def test_read_error_on_unreadable_path_is_loud(self, tmp_path: Path):
        # A path that stat()s but cannot be read as text (a directory) raises a
        # DocumentReadError with a real message, never a bare None.
        d = tmp_path / "adir"
        d.mkdir()
        with pytest.raises(DocumentReadError, match="cannot read confluence export"):
            read_confluence_export(d)
