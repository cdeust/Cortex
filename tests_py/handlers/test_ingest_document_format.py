"""Document format dispatch retains the existing explicit and extension rules."""

from pathlib import Path

import pytest

from mcp_server.handlers.ingest_document import _resolve_format


class TestResolveFormat:
    def test_explicit_docx(self):
        assert _resolve_format(Path("x.txt"), "docx") == "docx"

    def test_explicit_confluence(self):
        assert _resolve_format(Path("x.txt"), "confluence") == "confluence-export"

    def test_auto_docx_by_extension(self):
        assert _resolve_format(Path("a.docx"), "auto") == "docx"

    @pytest.mark.parametrize("ext", [".xml", ".xhtml", ".html", ".htm"])
    def test_auto_confluence_by_extension(self, ext):
        assert _resolve_format(Path("a" + ext), "auto") == "confluence-export"

    def test_unknown_extension_returns_empty(self):
        assert _resolve_format(Path("a.txt"), "auto") == ""

    def test_extension_is_case_insensitive(self):
        assert _resolve_format(Path("A.DOCX"), "auto") == "docx"
