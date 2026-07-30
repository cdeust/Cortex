"""Go/Swift/Rust parse_file_ast integration tests.

Split out of test_ast_parser.py (Extract Module, behavior-preserving — see
CHANGELOG's [Unreleased] entry for this PR): these three classes were
added by the issue #249 mutation-testing pass to close a real coverage
gap — `_extract_swift`/`_extract_rust` were never exercised through
`parse_file_ast` by any existing test, and the Go equivalent bypassed its
own wrapper by calling `extract_go_definitions` directly
(`TestGoExtractors` in `test_ast_extractors.py`) — and pushed
test_ast_parser.py to 405 lines, over this repo's 300-line/file cap
(CLAUDE.md, Code Style). Zero behavior change: same fixtures, same
assertions, same test names, moved as a unit.
"""

from __future__ import annotations

from mcp_server.core.ast_parser import is_available, parse_file_ast

_HAS_TREE_SITTER = is_available()


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
