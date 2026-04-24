"""Tests for WorkflowGraphNativeASTSource — the in-house AST source that
populates the L6 symbol ring when automatised-pipeline is absent.

Fixtures write small Python files to a tmp_path, point the source at
them, and assert SYMBOL + MEMBER_OF + IMPORTS are emitted in the shape
`ingest_symbol` / `ingest_ast_edge` expect.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_server.infrastructure.workflow_graph_source_native_ast import (
    WorkflowGraphNativeASTSource,
)


@pytest.fixture
def source() -> WorkflowGraphNativeASTSource:
    return WorkflowGraphNativeASTSource()


def _write(tmp: Path, rel: str, body: str) -> str:
    """Write a file under `tmp`, return its absolute path as a string."""
    p = tmp / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return str(p)


class TestEnabled:
    def test_always_enabled(self, source):
        """Native source is enabled unconditionally — regex fallback
        handles languages tree-sitter doesn't ship."""
        assert source.enabled() is True


class TestLoadSymbols:
    def test_empty_file_list_returns_empty(self, source):
        assert source.load_symbols([]) == []

    def test_unreadable_paths_are_skipped(self, source):
        assert source.load_symbols(["/no/such/file.py"]) == []

    def test_python_class_and_method_emit_symbol_rows(self, tmp_path, source):
        path = _write(
            tmp_path,
            "sample.py",
            "class Foo:\n"
            "    def bar(self):\n"
            "        return 1\n"
            "\n"
            "def top_level():\n"
            "    return 2\n",
        )
        syms = source.load_symbols([path])
        names = {s["qualified_name"] for s in syms}
        assert "Foo" in names
        assert "Foo.bar" in names
        assert "top_level" in names
        # Shape expected by ingest_symbol.
        for s in syms:
            assert s["file_path"] == path
            assert s["language"] == "python"
            assert s["symbol_type"] in {"class", "method", "function"}
            assert "qualified_name" in s
            assert s["domain"] == ""

    def test_non_source_files_skipped(self, tmp_path, source):
        """Markdown / text files have no language — saves fs.stat on
        every .md Claude touched."""
        md = _write(tmp_path, "note.md", "# hello")
        txt = _write(tmp_path, "stuff.txt", "plain")
        assert source.load_symbols([md, txt]) == []


class TestLoadASTEdges:
    def test_member_of_emitted_for_method(self, tmp_path, source):
        path = _write(
            tmp_path,
            "a.py",
            "class Foo:\n"
            "    def bar(self): ...\n"
            "    def baz(self): ...\n",
        )
        edges = source.load_ast_edges([path])
        member_of = [e for e in edges if e["kind"] == "member_of"]
        assert len(member_of) == 2
        for e in member_of:
            assert e["src_file"] == path
            assert e["dst_file"] == path
            assert e["dst_name"] == "Foo"
            assert e["src_name"].startswith("Foo.")
            assert e["confidence"] == 1.0
            assert "native-ast" in e["reason"]

    def test_imports_resolve_to_sibling_symbol(self, tmp_path, source):
        _write(
            tmp_path,
            "lib.py",
            "def helper():\n    return 1\n",
        )
        caller = _write(
            tmp_path,
            "user.py",
            "from lib import helper\n\n"
            "def go():\n    return helper()\n",
        )
        lib = str(tmp_path / "lib.py")
        edges = source.load_ast_edges([str(tmp_path / "user.py"), lib])
        imports = [e for e in edges if e["kind"] == "imports"]
        # At least one IMPORTS edge: user.py → helper in lib.py.
        matches = [
            e
            for e in imports
            if e["src_file"] == caller
            and e["dst_file"] == lib
            and e["dst_name"] == "helper"
        ]
        assert matches, f"expected user.py→lib.helper import edge, got {imports}"
        e = matches[0]
        assert e["src_name"] == ""  # file-level import
        assert e["confidence"] == 1.0

    def test_unresolved_imports_skipped(self, tmp_path, source):
        path = _write(tmp_path, "a.py", "import nonexistent_external_pkg\n")
        edges = source.load_ast_edges([path])
        # No target file → no import edge.
        assert all(e["kind"] != "imports" for e in edges)

    def test_empty_file_list_returns_empty(self, source):
        assert source.load_ast_edges([]) == []


class TestFileCap:
    def test_max_files_cap_honored(self, tmp_path, source, monkeypatch):
        """Runaway callers get bounded work, not a freeze."""
        import mcp_server.infrastructure.workflow_graph_source_native_ast as mod

        monkeypatch.setattr(mod, "_MAX_FILES_PER_CALL", 3)
        paths = [
            _write(tmp_path, f"f{i}.py", "def a(): ...\n") for i in range(10)
        ]
        syms = source.load_symbols(paths)
        # 3 files × 1 symbol each = 3 symbols max.
        assert len(syms) == 3
