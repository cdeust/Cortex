"""Tests for ast_extractors — per-language tree-sitter extraction.

Tests adapt to the environment:
- With tree-sitter: verifies extractors directly via tree-sitter parser
- Without tree-sitter: verifies parse_file_ast regex fallback handles these languages
"""

from __future__ import annotations

from mcp_server.core.ast_parser import is_available, parse_file_ast

_HAS_TREE_SITTER = is_available()


class TestPythonExtractors:
    def test_decorated_function(self) -> None:
        code = b"""
@app.route("/api")
def handle_request(req):
    pass

@staticmethod
def helper():
    pass
"""
        if _HAS_TREE_SITTER:
            from mcp_server.core.ast_extractors import extract_python_definitions
            from tree_sitter_language_pack import get_parser

            tree = get_parser("python").parse(code)
            defs = extract_python_definitions(tree.root_node, code)
            names = [d.name for d in defs]
            assert "handle_request" in names
            assert "helper" in names
        else:
            r = parse_file_ast("test.py", code)
            assert r.language == "python"
            assert isinstance(r.definitions, list)

    def test_nested_class_methods(self) -> None:
        code = b"""
class Outer:
    def method_a(self):
        pass

    def method_b(self, x):
        pass
"""
        if _HAS_TREE_SITTER:
            from mcp_server.core.ast_extractors import extract_python_definitions
            from tree_sitter_language_pack import get_parser

            tree = get_parser("python").parse(code)
            defs = extract_python_definitions(tree.root_node, code)
            names = [d.name for d in defs]
            assert "Outer" in names
            assert "Outer.method_a" in names
            assert "Outer.method_b" in names
        else:
            r = parse_file_ast("test.py", code)
            assert r.language == "python"

    def test_async_function(self) -> None:
        code = b"async def fetch_data(url: str) -> dict:\n    pass\n"
        if _HAS_TREE_SITTER:
            from mcp_server.core.ast_extractors import extract_python_definitions
            from tree_sitter_language_pack import get_parser

            tree = get_parser("python").parse(code)
            defs = extract_python_definitions(tree.root_node, code)
            assert any(d.name == "fetch_data" for d in defs)
        else:
            r = parse_file_ast("test.py", code)
            assert r.language == "python"


class TestJSExtractors:
    def test_exported_class_with_methods(self) -> None:
        code = b"""
export class Router {
  get(path) {
    return this;
  }
  post(path) {
    return this;
  }
}
"""
        if _HAS_TREE_SITTER:
            from mcp_server.core.ast_extractors import extract_js_definitions
            from tree_sitter_language_pack import get_parser

            tree = get_parser("javascript").parse(code)
            defs = extract_js_definitions(tree.root_node, code)
            names = [d.name for d in defs]
            assert "Router" in names
            assert "Router.get" in names
            assert "Router.post" in names
        else:
            r = parse_file_ast("router.js", code)
            assert r.language == "javascript"

    def test_interface_and_type(self) -> None:
        code = b"""
export interface Config { key: string; }
export type Options = { verbose: boolean; };
"""
        if _HAS_TREE_SITTER:
            from mcp_server.core.ast_extractors import extract_js_definitions
            from tree_sitter_language_pack import get_parser

            tree = get_parser("typescript").parse(code)
            defs = extract_js_definitions(tree.root_node, code)
            kinds = {d.name: d.kind for d in defs}
            assert kinds.get("Config") == "interface"
            assert kinds.get("Options") == "type"
        else:
            r = parse_file_ast("types.ts", code)
            assert r.language == "typescript"


class TestGoExtractors:
    def test_go_struct_and_method(self) -> None:
        code = b"""
package main

type Server struct {
    port int
}

func (s *Server) Start() error {
    return nil
}

func NewServer(port int) *Server {
    return &Server{port: port}
}
"""
        if _HAS_TREE_SITTER:
            from mcp_server.core.ast_extractors_extra import extract_go_definitions
            from tree_sitter_language_pack import get_parser

            tree = get_parser("go").parse(code)
            defs = extract_go_definitions(tree.root_node, code)
            names = [d.name for d in defs]
            assert "Server" in names
            assert "Server.Start" in names
            assert "NewServer" in names
        else:
            r = parse_file_ast("main.go", code)
            assert r.language == "go"


class TestWalkType:
    """`_walk_type` is the shared descendant search behind every extractor
    module (clike, extra, jvm, scripting), so its depth ceiling and its
    ordering are contracts, not implementation details.
    """

    def _js_root(self, code: bytes):
        from tree_sitter_language_pack import get_parser

        return get_parser("javascript").parse(code).root_node

    def test_deep_nesting_does_not_exhaust_the_interpreter_stack(self) -> None:
        """Regression: the recursive form raised RecursionError at AST depth
        ~1003 (default limit 1000). 1500 is comfortably past that, and no
        caller anywhere in mcp_server/ catches RecursionError.
        """
        if not _HAS_TREE_SITTER:
            return
        from mcp_server.core.ast_extractors import _walk_type

        depth = 1500
        code = (b"(" * depth) + b"1" + (b")" * depth) + b";"
        assert _walk_type(self._js_root(code), "import_statement") == []

    def test_returns_matches_in_document_order(self) -> None:
        if not _HAS_TREE_SITTER:
            return
        from mcp_server.core.ast_extractors import _walk_type

        code = b"import a from 'a';\nimport b from 'b';\nimport c from 'c';\n"
        found = _walk_type(self._js_root(code), "import_statement")
        starts = [n.start_byte for n in found]
        assert len(found) == 3
        assert starts == sorted(starts)

    def test_includes_the_start_node_itself(self) -> None:
        if not _HAS_TREE_SITTER:
            return
        from mcp_server.core.ast_extractors import _walk_type

        root = self._js_root(b"const x = 1;\n")
        assert _walk_type(root, root.type) == [root]

    def test_returns_empty_when_nothing_matches(self) -> None:
        if not _HAS_TREE_SITTER:
            return
        from mcp_server.core.ast_extractors import _walk_type

        root = self._js_root(b"const x = 1;\n")
        assert _walk_type(root, "no_such_node_type") == []
