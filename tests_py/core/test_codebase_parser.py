"""Tests for codebase_parser — regex-based source file analysis."""

from __future__ import annotations

from mcp_server.core.codebase_parser import (
    build_memory_content,
    detect_language,
    parse_file,
)


class TestDetectLanguage:
    def test_python(self) -> None:
        assert detect_language("src/main.py") == "python"

    def test_typescript(self) -> None:
        assert detect_language("components/App.tsx") == "typescript"

    def test_go(self) -> None:
        assert detect_language("cmd/server/main.go") == "go"

    def test_rust(self) -> None:
        assert detect_language("src/lib.rs") == "rust"

    def test_swift(self) -> None:
        assert detect_language("Sources/App/main.swift") == "swift"

    def test_unknown(self) -> None:
        assert detect_language("README.md") == "unknown"


class TestParsePython:
    SAMPLE = '''"""Authentication middleware."""

from flask import request, abort
from auth.tokens import verify_jwt
import logging

class AuthMiddleware:
    """Handles authentication."""
    pass

def authenticate_request(req):
    """Authenticate an incoming request."""
    token = req.headers.get("Authorization")
    return verify_jwt(token)

async def refresh_token(user_id: str) -> dict:
    pass
'''

    def test_imports(self) -> None:
        result = parse_file("auth/middleware.py", self.SAMPLE)
        modules = [i.module for i in result.imports]
        assert "flask" in modules
        assert "auth.tokens" in modules
        assert "logging" in modules

    def test_from_import_names(self) -> None:
        result = parse_file("auth/middleware.py", self.SAMPLE)
        flask_imp = next(i for i in result.imports if i.module == "flask")
        assert "request" in flask_imp.names
        assert "abort" in flask_imp.names

    def test_class(self) -> None:
        result = parse_file("auth/middleware.py", self.SAMPLE)
        classes = [d for d in result.definitions if d.kind == "class"]
        assert len(classes) == 1
        assert classes[0].name == "AuthMiddleware"

    def test_functions(self) -> None:
        result = parse_file("auth/middleware.py", self.SAMPLE)
        funcs = [d for d in result.definitions if d.kind == "function"]
        names = [f.name for f in funcs]
        assert "authenticate_request" in names
        assert "refresh_token" in names

    def test_docstring(self) -> None:
        result = parse_file("auth/middleware.py", self.SAMPLE)
        assert "Authentication middleware" in result.docstring

    def test_content_hash(self) -> None:
        r1 = parse_file("a.py", "def foo(): pass")
        r2 = parse_file("a.py", "def foo(): pass")
        r3 = parse_file("a.py", "def bar(): pass")
        assert r1.content_hash == r2.content_hash
        assert r1.content_hash != r3.content_hash

    def test_language(self) -> None:
        result = parse_file("auth/middleware.py", self.SAMPLE)
        assert result.language == "python"


class TestParseTypeScript:
    SAMPLE = """import { Request, Response } from 'express';
import jwt from 'jsonwebtoken';

export interface AuthConfig {
  secret: string;
  expiry: number;
}

export type TokenPayload = {
  userId: string;
  role: string;
};

export class AuthService {
  constructor(private config: AuthConfig) {}
}

export async function verifyToken(token: string): Promise<TokenPayload> {
  return jwt.verify(token, config.secret);
}
"""

    def test_imports(self) -> None:
        result = parse_file("auth/service.ts", self.SAMPLE)
        modules = [i.module for i in result.imports]
        assert "express" in modules
        assert "jsonwebtoken" in modules

    def test_interface(self) -> None:
        result = parse_file("auth/service.ts", self.SAMPLE)
        interfaces = [d for d in result.definitions if d.kind == "interface"]
        assert any(i.name == "AuthConfig" for i in interfaces)

    def test_type_alias(self) -> None:
        result = parse_file("auth/service.ts", self.SAMPLE)
        types = [d for d in result.definitions if d.kind == "type"]
        assert any(t.name == "TokenPayload" for t in types)

    def test_class(self) -> None:
        result = parse_file("auth/service.ts", self.SAMPLE)
        classes = [d for d in result.definitions if d.kind == "class"]
        assert any(c.name == "AuthService" for c in classes)

    def test_function(self) -> None:
        result = parse_file("auth/service.ts", self.SAMPLE)
        funcs = [d for d in result.definitions if d.kind == "function"]
        assert any(f.name == "verifyToken" for f in funcs)


class TestParseGo:
    SAMPLE = """package auth

import (
    "context"
    "fmt"
    "github.com/golang-jwt/jwt/v5"
)

type AuthService struct {
    secret string
}

type TokenValidator interface {
    Validate(ctx context.Context, token string) error
}

func NewAuthService(secret string) *AuthService {
    return &AuthService{secret: secret}
}

func (s *AuthService) Validate(ctx context.Context, token string) error {
    return nil
}
"""

    def test_imports(self) -> None:
        result = parse_file("auth/service.go", self.SAMPLE)
        modules = [i.module for i in result.imports]
        assert "context" in modules
        assert "github.com/golang-jwt/jwt/v5" in modules

    def test_struct(self) -> None:
        result = parse_file("auth/service.go", self.SAMPLE)
        structs = [d for d in result.definitions if d.kind == "struct"]
        assert any(s.name == "AuthService" for s in structs)

    def test_interface(self) -> None:
        result = parse_file("auth/service.go", self.SAMPLE)
        interfaces = [d for d in result.definitions if d.kind == "interface"]
        assert any(i.name == "TokenValidator" for i in interfaces)

    def test_functions(self) -> None:
        result = parse_file("auth/service.go", self.SAMPLE)
        funcs = [d for d in result.definitions if d.kind == "function"]
        names = [f.name for f in funcs]
        assert "NewAuthService" in names
        assert "Validate" in names


class TestBuildMemoryContent:
    def test_includes_path(self) -> None:
        analysis = parse_file("src/main.py", "def hello(): pass")
        content = build_memory_content(analysis)
        assert "# File: src/main.py" in content

    def test_includes_definitions(self) -> None:
        analysis = parse_file("src/main.py", "class Foo:\n    pass\ndef bar(): pass")
        content = build_memory_content(analysis)
        assert "class: Foo" in content
        assert "function: bar" in content

    def test_includes_imports(self) -> None:
        analysis = parse_file("src/main.py", "import os\nfrom sys import argv")
        content = build_memory_content(analysis)
        assert "os" in content
        assert "sys" in content

    def test_includes_line_count(self) -> None:
        analysis = parse_file("src/main.py", "a\nb\nc")
        content = build_memory_content(analysis)
        assert "3 lines" in content
