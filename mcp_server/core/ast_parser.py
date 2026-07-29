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
from typing import TYPE_CHECKING, cast

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

# Languages supported by our AST queries.
#
# Deliberately NOT typed as the language pack's SupportedLanguage: that union
# is narrower than the runtime. tree-sitter-language-pack 1.6.2 omits "csharp"
# from the Literal in its __init__.pyi, yet get_parser("csharp").parse() works
# and returns a clean compilation_unit (verified against 1.6.2 on 2026-07-29).
# Annotating with the union would therefore reject a language this repo really
# does parse — .cs files have extractors, a mapping and tests here.
AST_SUPPORTED = {
    "python",
    "typescript",
    "javascript",
    "go",
    "rust",
    "swift",
    "java",
    "kotlin",
    "c",
    "cpp",
    "csharp",
    "ruby",
    "php",
}


def is_available() -> bool:
    """Check if tree-sitter is installed."""
    try:
        from tree_sitter_language_pack import get_parser  # noqa: PLC0415, F401 — optional-feature probe: ImportError here is a handled degraded mode

        return True
    except ImportError:
        return False


def _get_extractor_and_tree(language: str, content: bytes) -> tuple | None:
    """Get tree-sitter extractor and parsed tree, or None for fallback."""
    if language not in AST_SUPPORTED:
        return None
    extractor = _EXTRACTORS.get(language)
    if not extractor:
        return None
    try:
        from tree_sitter_language_pack import get_parser  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode
    except ImportError:
        return None

    # cast, not a wider annotation: 1.6.2's stub types this parameter as a
    # Literal union that is missing "csharp" (see AST_SUPPORTED above), so the
    # membership guard at the top of this function — not the stub — is what
    # establishes that `language` names a grammar the pack can load.
    tree = get_parser(cast("SupportedLanguage", language)).parse(content)
    return extractor, tree


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


_EXTRACTORS = {
    "python": _extract_python,
    "javascript": _extract_js,
    "typescript": _extract_js,
    "go": _extract_go,
    "swift": _extract_swift,
    "rust": _extract_rust,
    **build_extra_extractors(),
}
