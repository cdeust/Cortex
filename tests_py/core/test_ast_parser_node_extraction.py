"""Direct unit tests for ast_parser's docstring/comment-extraction helpers.

Split out of test_ast_parser.py (Extract Module, behavior-preserving — see
CHANGELOG's [Unreleased] entry for this PR): `_extract_module_doc` and
`_node_text` are exercised here through fake, duck-typed `_FakeNode`
instances rather than through `parse_file_ast`, so they belong with the
other direct-unit-test group, not the parse_file_ast integration classes
that make up the rest of test_ast_parser.py. Growing that file with the
Go/Swift/Rust wrapper classes (issue #249 mutation-testing pass) pushed it
to 405 lines, over this repo's 300-line/file cap (CLAUDE.md, Code Style);
this split is the fix, not a rename — zero behavior change, same fake-Node
fixtures, same assertions, same test names, moved as a unit.
"""

from __future__ import annotations

from mcp_server.core.ast_parser import _extract_module_doc, _node_text


class _FakeNode:
    """Minimal duck-typed stand-in for a tree_sitter.Node.

    ast_parser's docstring/comment extraction only reads `.type`,
    `.children`, `.start_byte`, `.end_byte` — a real grammar is not needed
    to pin these functions' branches precisely.
    """

    def __init__(
        self,
        node_type: str,
        children: list["_FakeNode"] | None = None,
        start_byte: int = 0,
        end_byte: int = 0,
    ) -> None:
        self.type = node_type
        self.children = children or []
        self.start_byte = start_byte
        self.end_byte = end_byte


class TestExtractModuleDoc:
    """Direct unit tests for the docstring/comment-extraction branches —
    fake nodes pin exact behavior without depending on a specific grammar's
    tree shape (issue #249 mutation-testing pass)."""

    def test_no_children_returns_empty(self) -> None:
        root = _FakeNode("module", children=[])
        assert _extract_module_doc(root, "python", b"") == ""

    def test_python_bare_string_first_child(self) -> None:
        source = b'"""hello"""'
        string_node = _FakeNode("string", start_byte=0, end_byte=len(source))
        root = _FakeNode("module", children=[string_node])
        assert _extract_module_doc(root, "python", source) == "hello"

    def test_python_expression_statement_wrapper(self) -> None:
        source = b'"""Xylophone is great."""'
        string_node = _FakeNode("string", start_byte=0, end_byte=len(source))
        other = _FakeNode("other")
        expr_stmt = _FakeNode("expression_statement", children=[string_node, other])
        root = _FakeNode("module", children=[expr_stmt])
        assert _extract_module_doc(root, "python", source) == "Xylophone is great."

    def test_python_docstring_truncated_at_200(self) -> None:
        body = "x" * 250
        source = f'"""{body}"""'.encode()
        string_node = _FakeNode("string", start_byte=0, end_byte=len(source))
        root = _FakeNode("module", children=[string_node])
        doc = _extract_module_doc(root, "python", source)
        assert len(doc) == 200

    def test_non_python_comment_first_child(self) -> None:
        source = b"# Xray diagnostics."
        comment = _FakeNode("comment", start_byte=0, end_byte=len(source))
        root = _FakeNode("module", children=[comment])
        assert _extract_module_doc(root, "javascript", source) == "Xray diagnostics."

    def test_comment_truncated_at_200(self) -> None:
        source = ("# " + "y" * 250).encode()
        comment = _FakeNode("comment", start_byte=0, end_byte=len(source))
        root = _FakeNode("module", children=[comment])
        doc = _extract_module_doc(root, "javascript", source)
        assert len(doc) == 200

    def test_neither_string_nor_comment_returns_empty(self) -> None:
        root = _FakeNode("module", children=[_FakeNode("class_declaration")])
        assert _extract_module_doc(root, "go", b"") == ""


class TestNodeText:
    def test_extracts_slice_as_utf8(self) -> None:
        source = b"hello world"
        node = _FakeNode("identifier", start_byte=0, end_byte=5)
        assert _node_text(node, source) == "hello"

    def test_replaces_invalid_utf8_instead_of_raising(self) -> None:
        """`errors="replace"` must survive a resolver swap, per issue #249:
        an invalid error-handler name (a stub/version mismatch) raises
        LookupError here instead of degrading gracefully."""
        source = b"\xff\xfe"
        node = _FakeNode("raw", start_byte=0, end_byte=len(source))
        text = _node_text(node, source)
        assert isinstance(text, str)
