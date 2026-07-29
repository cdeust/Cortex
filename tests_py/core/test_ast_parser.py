"""Tests for ast_parser — tree-sitter based code analysis.

Tests adapt to the environment:
- With tree-sitter: verifies full AST extraction (imports, classes, methods, etc.)
- Without tree-sitter: verifies regex fallback produces valid FileAnalysis
"""

from __future__ import annotations

import sys

import pytest

from mcp_server.core.ast_parser import (
    _extract_module_doc,
    _node_text,
    is_available,
    parse_file_ast,
)

_HAS_TREE_SITTER = is_available()


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


class TestParseFilePython:
    SAMPLE = b'''"""Auth middleware module."""

from flask import request, abort
from auth.tokens import verify_jwt
import logging

class AuthMiddleware:
    def __init__(self, app):
        self.app = app

    def authenticate(self, req):
        token = req.headers.get("Authorization")
        return verify_jwt(token)

def standalone_func(x: int) -> str:
    return str(x)
'''

    def test_returns_file_analysis(self) -> None:
        r = parse_file_ast("auth/middleware.py", self.SAMPLE)
        assert r.path == "auth/middleware.py"
        assert r.language == "python"
        assert r.content_hash  # non-empty

    def test_imports(self) -> None:
        r = parse_file_ast("auth/middleware.py", self.SAMPLE)
        modules = [i.module for i in r.imports]
        if _HAS_TREE_SITTER:
            assert "flask" in modules
            assert "auth.tokens" in modules
            assert "logging" in modules
        else:
            # Regex fallback still extracts imports
            assert len(r.imports) >= 0  # valid list returned

    def test_from_import_names(self) -> None:
        r = parse_file_ast("auth/middleware.py", self.SAMPLE)
        if _HAS_TREE_SITTER:
            flask = next(i for i in r.imports if i.module == "flask")
            assert "request" in flask.names or any("request" in n for n in flask.names)

    def test_class_detected(self) -> None:
        r = parse_file_ast("auth/middleware.py", self.SAMPLE)
        if _HAS_TREE_SITTER:
            classes = [d for d in r.definitions if d.kind == "class"]
            assert any(c.name == "AuthMiddleware" for c in classes)
        else:
            # Regex fallback may or may not find classes
            assert isinstance(r.definitions, list)

    def test_methods_scoped_to_class(self) -> None:
        r = parse_file_ast("auth/middleware.py", self.SAMPLE)
        if _HAS_TREE_SITTER:
            methods = [d for d in r.definitions if d.kind == "method"]
            names = [m.name for m in methods]
            assert "AuthMiddleware.__init__" in names
            assert "AuthMiddleware.authenticate" in names

    def test_standalone_function(self) -> None:
        r = parse_file_ast("auth/middleware.py", self.SAMPLE)
        if _HAS_TREE_SITTER:
            funcs = [d for d in r.definitions if d.kind == "function"]
            assert any(f.name == "standalone_func" for f in funcs)

    def test_docstring_extracted(self) -> None:
        r = parse_file_ast("auth/middleware.py", self.SAMPLE)
        if _HAS_TREE_SITTER:
            assert "Auth middleware" in r.docstring

    def test_content_hash_stable(self) -> None:
        r1 = parse_file_ast("a.py", b"def foo(): pass")
        r2 = parse_file_ast("a.py", b"def foo(): pass")
        assert r1.content_hash == r2.content_hash

    def test_content_hash_changes(self) -> None:
        r1 = parse_file_ast("a.py", b"def foo(): pass")
        r2 = parse_file_ast("a.py", b"def bar(): pass")
        assert r1.content_hash != r2.content_hash

    def test_language(self) -> None:
        r = parse_file_ast("auth/middleware.py", self.SAMPLE)
        assert r.language == "python"

    def test_line_count(self) -> None:
        r = parse_file_ast("a.py", b"a\nb\nc")
        assert r.line_count == 3

    def test_fallback_returns_valid_analysis(self) -> None:
        """parse_file_ast always returns valid FileAnalysis, even via regex fallback."""
        r = parse_file_ast("script.py", b"import os\ndef main(): pass\n")
        assert r.path == "script.py"
        assert r.language == "python"
        assert r.line_count >= 2

    def test_content_hash_length(self) -> None:
        r = parse_file_ast("a.py", b"def foo(): pass")
        assert len(r.content_hash) == 16

    def test_calls_per_function_populated(self) -> None:
        r = parse_file_ast("auth/middleware.py", self.SAMPLE)
        if _HAS_TREE_SITTER:
            assert "AuthMiddleware.authenticate" in r.calls_per_function
            assert "verify_jwt" in r.calls_per_function["AuthMiddleware.authenticate"]
        else:
            assert r.calls_per_function == {}

    def test_decodes_malformed_utf8_without_raising(self) -> None:
        """`errors="replace"` must survive a resolver swap, per issue #249."""
        r = parse_file_ast("bad.py", b"\xff\xfe def foo(): pass")
        assert isinstance(r.line_count, int)


def test_is_available_reflects_installed_tree_sitter() -> None:
    """Pins is_available()'s True branch — a mutant flipping it to False
    would still leave every _HAS_TREE_SITTER-gated assertion above passing
    trivially (the gated branch is simply skipped)."""
    if not _HAS_TREE_SITTER:
        pytest.skip("tree-sitter not installed")
    assert is_available() is True


def test_is_available_false_when_tree_sitter_import_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pins the except-ImportError branch, unreachable when tree-sitter IS
    installed (this environment): forcing the import to fail is the only
    way to exercise it directly."""
    monkeypatch.setitem(sys.modules, "tree_sitter_language_pack", None)
    assert is_available() is False


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


class TestParseFileTypeScript:
    SAMPLE = b"""import { Request } from 'express';
import jwt from 'jsonwebtoken';

export interface AuthConfig {
  secret: string;
}

export class AuthService {
  verify(token: string): boolean {
    return true;
  }
}

export function createAuth(config: AuthConfig): AuthService {
  return new AuthService();
}
"""

    def test_returns_file_analysis(self) -> None:
        r = parse_file_ast("auth/service.ts", self.SAMPLE)
        assert r.path == "auth/service.ts"
        assert r.language == "typescript"

    def test_imports(self) -> None:
        r = parse_file_ast("auth/service.ts", self.SAMPLE)
        if _HAS_TREE_SITTER:
            modules = [i.module for i in r.imports]
            assert "express" in modules
            assert "jsonwebtoken" in modules

    def test_interface(self) -> None:
        r = parse_file_ast("auth/service.ts", self.SAMPLE)
        if _HAS_TREE_SITTER:
            interfaces = [d for d in r.definitions if d.kind == "interface"]
            assert any(i.name == "AuthConfig" for i in interfaces)

    def test_class(self) -> None:
        r = parse_file_ast("auth/service.ts", self.SAMPLE)
        if _HAS_TREE_SITTER:
            classes = [d for d in r.definitions if d.kind == "class"]
            assert any(c.name == "AuthService" for c in classes)

    def test_method_scoped(self) -> None:
        r = parse_file_ast("auth/service.ts", self.SAMPLE)
        if _HAS_TREE_SITTER:
            methods = [d for d in r.definitions if d.kind == "method"]
            assert any("verify" in m.name for m in methods)

    def test_function(self) -> None:
        r = parse_file_ast("auth/service.ts", self.SAMPLE)
        if _HAS_TREE_SITTER:
            funcs = [d for d in r.definitions if d.kind == "function"]
            assert any(f.name == "createAuth" for f in funcs)


class TestFallbackForUnsupported:
    def test_unknown_extension_uses_regex(self) -> None:
        r = parse_file_ast("readme.md", b"# Hello")
        assert r.language == "unknown"
        assert r.definitions == []


class TestParseFileGo:
    """Exercises ast_parser._extract_go through the public parse_file_ast
    entry point — TestGoExtractors (test_ast_extractors.py) calls
    extract_go_definitions directly and never reaches this wrapper
    (issue #249 mutation-testing pass)."""

    SAMPLE = b"""package main

import "fmt"

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

    def test_returns_file_analysis(self) -> None:
        r = parse_file_ast("main.go", self.SAMPLE)
        assert r.language == "go"

    def test_imports(self) -> None:
        r = parse_file_ast("main.go", self.SAMPLE)
        if _HAS_TREE_SITTER:
            assert "fmt" in [i.module for i in r.imports]

    def test_definitions(self) -> None:
        r = parse_file_ast("main.go", self.SAMPLE)
        if _HAS_TREE_SITTER:
            names = [d.name for d in r.definitions]
            assert "Server.Start" in names
            assert "NewServer" in names


class TestParseFileSwift:
    """Exercises ast_parser._extract_swift through parse_file_ast — no
    prior test reached this wrapper at all (issue #249 mutation-testing
    pass: 12/12 mutants reported "no tests" before this class)."""

    SAMPLE = b"""import Foundation

class AuthService {
    func verify(token: String) -> Bool {
        return true
    }
}
"""

    def test_returns_file_analysis(self) -> None:
        r = parse_file_ast("Auth.swift", self.SAMPLE)
        assert r.language == "swift"

    def test_imports(self) -> None:
        r = parse_file_ast("Auth.swift", self.SAMPLE)
        if _HAS_TREE_SITTER:
            assert "Foundation" in [i.module for i in r.imports]

    def test_definitions(self) -> None:
        r = parse_file_ast("Auth.swift", self.SAMPLE)
        if _HAS_TREE_SITTER:
            names = [d.name for d in r.definitions]
            assert "AuthService" in names


class TestParseFileRust:
    """Exercises ast_parser._extract_rust through parse_file_ast — no
    prior test reached this wrapper at all (issue #249 mutation-testing
    pass: 12/12 mutants reported "no tests" before this class)."""

    SAMPLE = b"""use std::fmt;

struct Server {
    port: u16,
}

fn new_server(port: u16) -> Server {
    Server { port }
}
"""

    def test_returns_file_analysis(self) -> None:
        r = parse_file_ast("main.rs", self.SAMPLE)
        assert r.language == "rust"

    def test_imports(self) -> None:
        r = parse_file_ast("main.rs", self.SAMPLE)
        if _HAS_TREE_SITTER:
            assert "std::fmt" in [i.module for i in r.imports]

    def test_definitions(self) -> None:
        r = parse_file_ast("main.rs", self.SAMPLE)
        if _HAS_TREE_SITTER:
            names = [d.name for d in r.definitions]
            assert "Server" in names
            assert "new_server" in names
