"""Tree-sitter AST parser — structured code analysis with cross-file resolution.

Replaces regex-based extraction with proper AST parsing. Extracts:
- Imports with resolved target files
- Function/method definitions with scope
- Class definitions with inheritance
- Function call sites for call graph edges
- Class-method containment

Falls back to regex parser if tree-sitter is not installed.

Pure business logic — no I/O. Callers pass file content as bytes.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, TypeGuard

from mcp_server.core.ast_extractor_registry import build_extra_extractors
from mcp_server.core.codebase_parser import (
    FileAnalysis,
    ImportInfo,
    SymbolDef,
    detect_language,
)
from mcp_server.core.codebase_parser import parse_file
from mcp_server.core.ast_extractors import (
    extract_calls_per_function,
    extract_calls_generic,
    extract_python_definitions,
    extract_python_imports,
    extract_js_definitions,
    extract_js_imports,
)
from mcp_server.core.ast_extractors_extra import (
    extract_go_definitions,
    extract_go_imports,
    extract_swift_definitions,
    extract_swift_imports,
    extract_rust_definitions,
    extract_rust_imports,
)

if TYPE_CHECKING:
    from tree_sitter import Node
    from tree_sitter_language_pack import SupportedLanguage

    from mcp_server.core.ast_extractor_registry import Extractor


def is_available() -> bool:
    """Check if tree-sitter is installed."""
    try:
        from tree_sitter_language_pack import get_parser  # noqa: PLC0415, F401 — optional-feature probe: ImportError here is a handled degraded mode

        return True
    except ImportError:
        return False


def _is_ast_language(language: str) -> TypeGuard[SupportedLanguage]:
    """Narrow a detected language name to the language pack's literal type.

    Sound by construction: `AST_SUPPORTED` is declared
    `frozenset[SupportedLanguage]`, so a name the pack does not ship fails
    the type check at its definition rather than silently widening here.
    """
    return language in AST_SUPPORTED


def _get_extractor_and_tree(language: str, content: bytes) -> tuple | None:
    """Get tree-sitter extractor and parsed tree, or None for fallback."""
    if not _is_ast_language(language):
        return None
    try:
        from tree_sitter_language_pack import get_parser  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode
    except ImportError:
        return None

    tree = get_parser(language).parse(content)
    return _EXTRACTORS[language], tree


def parse_file_ast(path: str, content: bytes) -> FileAnalysis:
    """Parse a source file using tree-sitter AST.

    Args:
        path: Relative file path.
        content: Raw file content as bytes.

    Returns:
        FileAnalysis with imports, definitions, and content hash.
    """
    language = detect_language(path)
    content_hash = hashlib.sha256(content).hexdigest()[:16]
    text = content.decode(errors="replace")

    result = _get_extractor_and_tree(language, content)
    if not result:
        return parse_file(path, text)

    extractor, tree = result
    imports, definitions, calls = extractor(tree.root_node, content)
    docstring = _extract_module_doc(tree.root_node, language, content)
    # Caller-qualified call map — works across every language the
    # extractor covers because it targets tree-sitter node types shared
    # across grammars (function_definition, function_declaration,
    # method_definition, call, call_expression). Empty on regex fallback
    # or when a grammar doesn't expose those names.

    calls_per_function = extract_calls_per_function(tree.root_node, content)

    return FileAnalysis(
        path=path,
        language=language,
        content_hash=content_hash,
        imports=imports,
        definitions=definitions,
        docstring=docstring,
        line_count=text.count("\n") + 1,
        calls_per_function=calls_per_function,
    )


def _node_text(node: Node, source: bytes) -> str:
    """Extract text content of a tree-sitter node."""
    return source[node.start_byte : node.end_byte].decode(errors="replace")


def _extract_module_doc(
    root: Node,
    language: str,
    source: bytes,
) -> str:
    """Extract the module-level docstring."""
    if not root.children:
        return ""
    first = root.children[0]
    if language == "python":
        # tree-sitter may wrap as expression_statement or bare string
        target = first
        if first.type == "expression_statement" and first.children:
            target = first.children[0]
        if target.type == "string":
            text = _node_text(target, source).strip("\"'").strip()
            return text[:200]
    if first.type == "comment":
        return _node_text(first, source).lstrip("/#* ").strip()[:200]
    return ""


# ── Python extractor ─────────────────────────────────────────────────────


def _extract_python(
    root: Node,
    source: bytes,
) -> tuple[list[ImportInfo], list[SymbolDef], list[str]]:
    """Extract Python imports, definitions, and call sites."""

    imports = extract_python_imports(root, source)
    definitions = extract_python_definitions(root, source)
    calls = extract_calls_generic(root, source)
    return imports, definitions, calls


# ── JS/TS extractor ──────────────────────────────────────────────────────


def _extract_js(
    root: Node,
    source: bytes,
) -> tuple[list[ImportInfo], list[SymbolDef], list[str]]:
    """Extract JavaScript/TypeScript imports, definitions, and calls."""

    imports = extract_js_imports(root, source)
    definitions = extract_js_definitions(root, source)
    calls = extract_calls_generic(root, source)
    return imports, definitions, calls


# ── Go extractor ─────────────────────────────────────────────────────────


def _extract_go(
    root: Node,
    source: bytes,
) -> tuple[list[ImportInfo], list[SymbolDef], list[str]]:
    """Extract Go imports, definitions, and calls."""

    return (
        extract_go_imports(root, source),
        extract_go_definitions(root, source),
        extract_calls_generic(root, source),
    )


def _extract_swift(
    root: Node,
    source: bytes,
) -> tuple[list[ImportInfo], list[SymbolDef], list[str]]:
    """Extract Swift imports, definitions, and calls."""

    return (
        extract_swift_imports(root, source),
        extract_swift_definitions(root, source),
        extract_calls_generic(root, source),
    )


def _extract_rust(
    root: Node,
    source: bytes,
) -> tuple[list[ImportInfo], list[SymbolDef], list[str]]:
    """Extract Rust imports, definitions, and calls."""

    return (
        extract_rust_imports(root, source),
        extract_rust_definitions(root, source),
        extract_calls_generic(root, source),
    )


# Keyed by the language pack's own `SupportedLanguage` literal, not by `str`:
# that makes the type checker verify every key below against the grammars the
# pack actually ships, and it is what lets `_get_extractor_and_tree` hand
# `get_parser` a value of the type its signature asks for. The pack types that
# parameter `SupportedLanguage` up to 1.6.x and `str` from 1.9 on, so a plain
# `str` type-checks under one resolution of the dependency pin and fails under
# another — the divergence issue #253 was filed for. See the pin's own comment
# in pyproject.toml for the measured per-release type surface.
_EXTRACTORS: dict[SupportedLanguage, Extractor] = {
    "python": _extract_python,
    "javascript": _extract_js,
    "typescript": _extract_js,
    "go": _extract_go,
    "swift": _extract_swift,
    "rust": _extract_rust,
    **build_extra_extractors(),
}

# The extractor table IS the definition of "AST-supported": a language is
# supported exactly when queries exist for it. Derived rather than restated,
# so `_EXTRACTORS[language]` is total once `_is_ast_language` has narrowed —
# there is no second list that can drift out of step with this one.
AST_SUPPORTED: frozenset[SupportedLanguage] = frozenset(_EXTRACTORS)
