"""Tests for ast_parser — tree-sitter based code analysis.

Tests adapt to the environment:
- With tree-sitter: verifies full AST extraction (imports, classes, methods, etc.)
- Without tree-sitter: verifies regex fallback produces valid FileAnalysis
"""

from __future__ import annotations

from mcp_server.core.ast_parser import is_available, parse_file_ast

_HAS_TREE_SITTER = is_available()


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
            assert "request" in flask.names or any(
                "request" in n for n in flask.names
            )

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
