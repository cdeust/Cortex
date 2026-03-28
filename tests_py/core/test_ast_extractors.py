"""Tests for ast_extractors — per-language tree-sitter extraction."""

from __future__ import annotations

import pytest

from mcp_server.core.ast_parser import is_available

pytestmark = pytest.mark.skipif(not is_available(), reason="tree-sitter not installed")


class TestPythonExtractors:
    def test_decorated_function(self) -> None:
        from mcp_server.core.ast_extractors import extract_python_definitions
        from tree_sitter_language_pack import get_parser

        code = b"""
@app.route("/api")
def handle_request(req):
    pass

@staticmethod
def helper():
    pass
"""
        tree = get_parser("python").parse(code)
        defs = extract_python_definitions(tree.root_node, code)
        names = [d.name for d in defs]
        assert "handle_request" in names
        assert "helper" in names

    def test_nested_class_methods(self) -> None:
        from mcp_server.core.ast_extractors import extract_python_definitions
        from tree_sitter_language_pack import get_parser

        code = b"""
class Outer:
    def method_a(self):
        pass

    def method_b(self, x):
        pass
"""
        tree = get_parser("python").parse(code)
        defs = extract_python_definitions(tree.root_node, code)
        names = [d.name for d in defs]
        assert "Outer" in names
        assert "Outer.method_a" in names
        assert "Outer.method_b" in names

    def test_async_function(self) -> None:
        from mcp_server.core.ast_extractors import extract_python_definitions
        from tree_sitter_language_pack import get_parser

        code = b"async def fetch_data(url: str) -> dict:\n    pass\n"
        tree = get_parser("python").parse(code)
        defs = extract_python_definitions(tree.root_node, code)
        assert any(d.name == "fetch_data" for d in defs)


class TestJSExtractors:
    def test_exported_class_with_methods(self) -> None:
        from mcp_server.core.ast_extractors import extract_js_definitions
        from tree_sitter_language_pack import get_parser

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
        tree = get_parser("javascript").parse(code)
        defs = extract_js_definitions(tree.root_node, code)
        names = [d.name for d in defs]
        assert "Router" in names
        assert "Router.get" in names
        assert "Router.post" in names

    def test_interface_and_type(self) -> None:
        from mcp_server.core.ast_extractors import extract_js_definitions
        from tree_sitter_language_pack import get_parser

        code = b"""
export interface Config { key: string; }
export type Options = { verbose: boolean; };
"""
        tree = get_parser("typescript").parse(code)
        defs = extract_js_definitions(tree.root_node, code)
        kinds = {d.name: d.kind for d in defs}
        assert kinds.get("Config") == "interface"
        assert kinds.get("Options") == "type"


class TestCallExtraction:
    def test_python_calls(self) -> None:
        from mcp_server.core.ast_extractors import extract_calls_generic
        from tree_sitter_language_pack import get_parser

        code = b"""
result = process(data)
x = helper(1, 2)
obj.method()
"""
        tree = get_parser("python").parse(code)
        calls = extract_calls_generic(tree.root_node, code)
        assert "process" in calls
        assert "helper" in calls

    def test_js_calls(self) -> None:
        from mcp_server.core.ast_extractors import extract_calls_generic
        from tree_sitter_language_pack import get_parser

        code = b"""
const x = fetchData(url);
console.log("hello");
"""
        tree = get_parser("javascript").parse(code)
        calls = extract_calls_generic(tree.root_node, code)
        assert any("fetchData" in c for c in calls)


class TestGoExtractors:
    def test_go_struct_and_method(self) -> None:
        from mcp_server.core.ast_extractors_extra import extract_go_definitions
        from tree_sitter_language_pack import get_parser

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
        tree = get_parser("go").parse(code)
        defs = extract_go_definitions(tree.root_node, code)
        names = [d.name for d in defs]
        assert "Server" in names
        assert "Server.Start" in names
        assert "NewServer" in names
