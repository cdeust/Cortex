"""Tests for codebase_graph — import resolution, inheritance, communities, impact."""

from __future__ import annotations

import pytest

from mcp_server.core.codebase_parser import FileAnalysis, ImportInfo, SymbolDef
from mcp_server.core.codebase_graph import (
    resolve_import_to_file,
    resolve_all_imports,
    extract_inheritance,
    detect_communities,
    compute_impact,
    build_call_edges,
)
from mcp_server.core.codebase_type_resolver import resolve_type_references

_has_networkx = True
try:
    import networkx  # noqa: F401
except ImportError:
    _has_networkx = False


def _make_analysis(
    path: str,
    imports: list[ImportInfo] | None = None,
    definitions: list[SymbolDef] | None = None,
) -> FileAnalysis:
    return FileAnalysis(
        path=path,
        language="python",
        content_hash="abc",
        imports=imports or [],
        definitions=definitions or [],
    )


class TestResolveImportToFile:
    def test_absolute_python_import(self) -> None:
        known = {"auth/tokens.py", "auth/__init__.py", "main.py"}
        result = resolve_import_to_file("auth.tokens", "main.py", known)
        assert result == "auth/tokens.py"

    def test_relative_import(self) -> None:
        known = {"auth/tokens.py", "auth/middleware.py"}
        result = resolve_import_to_file(
            ".tokens",
            "auth/middleware.py",
            known,
            is_relative=True,
        )
        assert result == "auth/tokens.py"

    def test_strip_package_prefix(self) -> None:
        known = {"_adapters/ports.py", "server.py"}
        result = resolve_import_to_file(
            "mypackage._adapters.ports",
            "server.py",
            known,
        )
        assert result == "_adapters/ports.py"

    def test_init_file_resolution(self) -> None:
        known = {"auth/__init__.py", "main.py"}
        result = resolve_import_to_file("auth", "main.py", known)
        assert result == "auth/__init__.py"

    def test_no_match_returns_none(self) -> None:
        known = {"main.py"}
        result = resolve_import_to_file("nonexistent.module", "main.py", known)
        assert result is None

    def test_self_reference_filtered_in_resolve_all(self) -> None:
        """resolve_all_imports excludes self-referencing edges."""
        analyses = [
            _make_analysis("auth/tokens.py", [ImportInfo(module="auth.tokens")]),
        ]
        edges = resolve_all_imports(analyses)
        assert len(edges) == 0


class TestResolveAllImports:
    def test_cross_file_edges(self) -> None:
        analyses = [
            _make_analysis("main.py", [ImportInfo(module="auth.tokens")]),
            _make_analysis("auth/tokens.py", [ImportInfo(module="logging")]),
        ]
        edges = resolve_all_imports(analyses)
        assert ("main.py", "auth/tokens.py") in edges

    def test_external_imports_excluded(self) -> None:
        analyses = [
            _make_analysis("main.py", [ImportInfo(module="flask")]),
        ]
        edges = resolve_all_imports(analyses)
        assert len(edges) == 0


class TestExtractInheritance:
    def test_single_parent(self) -> None:
        analyses = [
            _make_analysis(
                "a.py",
                definitions=[
                    SymbolDef(name="Child", kind="class", signature="(Parent)"),
                ],
            ),
        ]
        edges = extract_inheritance(analyses)
        assert ("Child", "Parent") in edges

    def test_multiple_parents(self) -> None:
        analyses = [
            _make_analysis(
                "a.py",
                definitions=[
                    SymbolDef(name="MyClass", kind="class", signature="(Base, Mixin)"),
                ],
            ),
        ]
        edges = extract_inheritance(analyses)
        assert ("MyClass", "Base") in edges
        assert ("MyClass", "Mixin") in edges

    def test_object_excluded(self) -> None:
        analyses = [
            _make_analysis(
                "a.py",
                definitions=[
                    SymbolDef(name="Foo", kind="class", signature="(object)"),
                ],
            ),
        ]
        edges = extract_inheritance(analyses)
        assert len(edges) == 0

    def test_no_signature_no_edges(self) -> None:
        analyses = [
            _make_analysis(
                "a.py",
                definitions=[
                    SymbolDef(name="Foo", kind="class", signature=""),
                ],
            ),
        ]
        edges = extract_inheritance(analyses)
        assert len(edges) == 0

    def test_functions_ignored(self) -> None:
        analyses = [
            _make_analysis(
                "a.py",
                definitions=[
                    SymbolDef(name="foo", kind="function", signature="(x, y)"),
                ],
            ),
        ]
        edges = extract_inheritance(analyses)
        assert len(edges) == 0


class TestBuildCallEdges:
    def test_cross_file_call(self) -> None:
        analyses = [
            _make_analysis(
                "a.py",
                definitions=[
                    SymbolDef(name="helper", kind="function"),
                ],
            ),
            _make_analysis("b.py"),
        ]
        call_sites = {"b.py": ["helper"]}
        edges = build_call_edges(analyses, call_sites)
        assert any(
            e[0] == "b.py" and e[1] == "helper" and e[2] == "a.py" for e in edges
        )

    def test_same_file_excluded(self) -> None:
        analyses = [
            _make_analysis(
                "a.py",
                definitions=[
                    SymbolDef(name="foo", kind="function"),
                ],
            ),
        ]
        call_sites = {"a.py": ["foo"]}
        edges = build_call_edges(analyses, call_sites)
        assert len(edges) == 0


class TestTypeReferenceResolution:
    def test_swift_cross_file_type_usage(self) -> None:
        analyses = [
            _make_analysis(
                "Models/PRDDocument.swift",
                definitions=[
                    SymbolDef(name="PRDDocument", kind="class"),
                ],
            ),
            _make_analysis("Views/DocumentView.swift"),
        ]
        contents = {
            "Models/PRDDocument.swift": "class PRDDocument { var title: String }",
            "Views/DocumentView.swift": "struct DocumentView: View {\n  let doc: PRDDocument\n}",
        }
        edges = resolve_type_references(analyses, contents)
        assert ("Views/DocumentView.swift", "Models/PRDDocument.swift") in edges

    def test_no_self_reference(self) -> None:
        analyses = [
            _make_analysis(
                "a.swift",
                definitions=[
                    SymbolDef(name="Foo", kind="class"),
                ],
            ),
        ]
        contents = {"a.swift": "class Foo { func bar() -> Foo { return self } }"}
        edges = resolve_type_references(analyses, contents)
        assert len(edges) == 0

    def test_noise_types_filtered(self) -> None:
        analyses = [
            _make_analysis(
                "a.swift",
                definitions=[
                    SymbolDef(name="String", kind="type"),
                ],
            ),
            _make_analysis("b.swift"),
        ]
        contents = {
            "a.swift": "typealias X = String",
            "b.swift": 'let s: String = "hi"',
        }
        edges = resolve_type_references(analyses, contents)
        assert len(edges) == 0

    def test_short_names_filtered(self) -> None:
        analyses = [
            _make_analysis(
                "a.swift",
                definitions=[
                    SymbolDef(name="ID", kind="type"),
                ],
            ),
            _make_analysis("b.swift"),
        ]
        contents = {"a.swift": "typealias ID = Int", "b.swift": "let x: ID = 1"}
        edges = resolve_type_references(analyses, contents)
        assert len(edges) == 0

    def test_multiple_references(self) -> None:
        analyses = [
            _make_analysis(
                "models.swift",
                definitions=[
                    SymbolDef(name="UserProfile", kind="class"),
                    SymbolDef(name="AuthToken", kind="class"),
                ],
            ),
            _make_analysis("service.swift"),
            _make_analysis("view.swift"),
        ]
        contents = {
            "models.swift": "class UserProfile {}\nclass AuthToken {}",
            "service.swift": "func login() -> AuthToken { }",
            "view.swift": "func show(user: UserProfile) { }",
        }
        edges = resolve_type_references(analyses, contents)
        assert ("service.swift", "models.swift") in edges
        assert ("view.swift", "models.swift") in edges


@pytest.mark.skipif(not _has_networkx, reason="networkx not installed")
class TestDetectCommunities:
    def test_two_clusters(self) -> None:
        # Two disconnected groups
        file_edges = [
            ("a.py", "b.py"),
            ("c.py", "d.py"),
        ]
        communities = detect_communities(file_edges, [])
        # a and b should be in same community, c and d in another
        assert communities.get("a.py") == communities.get("b.py")
        assert communities.get("c.py") == communities.get("d.py")
        assert communities.get("a.py") != communities.get("c.py")

    def test_single_node(self) -> None:
        communities = detect_communities([("a.py", "a.py")], [])
        assert "a.py" in communities

    def test_empty_graph(self) -> None:
        communities = detect_communities([], [])
        assert communities == {}


class TestComputeImpact:
    def test_upstream(self) -> None:
        edges = [("b.py", "a.py"), ("c.py", "b.py")]
        result = compute_impact("a.py", edges, [])
        assert "b.py" in result["upstream"]

    def test_downstream(self) -> None:
        edges = [("a.py", "b.py"), ("b.py", "c.py")]
        result = compute_impact("a.py", edges, [])
        assert "b.py" in result["downstream"]

    def test_depth_limit(self) -> None:
        edges = [("a.py", "b.py"), ("b.py", "c.py"), ("c.py", "d.py"), ("d.py", "e.py")]
        result = compute_impact("a.py", edges, [], max_depth=2)
        assert "b.py" in result["downstream"]
        assert "c.py" in result["downstream"]
        # d.py is depth 3, should be excluded with max_depth=2
        assert "d.py" not in result["downstream"]

    def test_target_excluded_from_results(self) -> None:
        edges = [("b.py", "a.py")]
        result = compute_impact("a.py", edges, [])
        assert "a.py" not in result["upstream"]
        assert "a.py" not in result["downstream"]
