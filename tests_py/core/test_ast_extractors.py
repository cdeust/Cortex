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


class TestCallExtraction:
    def test_python_calls(self) -> None:
        code = b"""
result = process(data)
x = helper(1, 2)
obj.method()
"""
        if _HAS_TREE_SITTER:
            from mcp_server.core.ast_extractors import extract_calls_generic
            from tree_sitter_language_pack import get_parser

            tree = get_parser("python").parse(code)
            calls = extract_calls_generic(tree.root_node, code)
            assert "process" in calls
            assert "helper" in calls
        else:
            r = parse_file_ast("test.py", code)
            assert r.language == "python"

    def test_js_calls(self) -> None:
        code = b"""
const x = fetchData(url);
console.log("hello");
"""
        if _HAS_TREE_SITTER:
            from mcp_server.core.ast_extractors import extract_calls_generic
            from tree_sitter_language_pack import get_parser

            tree = get_parser("javascript").parse(code)
            calls = extract_calls_generic(tree.root_node, code)
            assert any("fetchData" in c for c in calls)
        else:
            r = parse_file_ast("app.js", code)
            assert r.language == "javascript"


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
