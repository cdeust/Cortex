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
from typing import TYPE_CHECKING

from mcp_server.core.codebase_parser import (
    FileAnalysis,
    ImportInfo,
    SymbolDef,
    detect_language,
)

if TYPE_CHECKING:
    from tree_sitter import Node

# Languages supported by our AST queries
AST_SUPPORTED = {"python", "typescript", "javascript", "go", "rust", "swift"}


def is_available() -> bool:
    """Check if tree-sitter is installed."""
    try:
        from tree_sitter_language_pack import get_parser  # noqa: F401

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
        from tree_sitter_language_pack import get_parser
    except ImportError:
        return None

    tree = get_parser(language).parse(content)
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
        from mcp_server.core.codebase_parser import parse_file

        return parse_file(path, text)

    extractor, tree = result
    imports, definitions, calls = extractor(tree.root_node, content)
    docstring = _extract_module_doc(tree.root_node, language, content)

    return FileAnalysis(
        path=path,
        language=language,
        content_hash=content_hash,
        imports=imports,
        definitions=definitions,
        docstring=docstring,
        line_count=text.count("\n") + 1,
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
    from mcp_server.core.ast_extractors import (
        extract_python_imports,
        extract_python_definitions,
        extract_calls_generic,
    )

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
    from mcp_server.core.ast_extractors import (
        extract_js_imports,
        extract_js_definitions,
        extract_calls_generic,
    )

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
    from mcp_server.core.ast_extractors import extract_calls_generic
    from mcp_server.core.ast_extractors_extra import (
        extract_go_imports,
        extract_go_definitions,
    )

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
    from mcp_server.core.ast_extractors import extract_calls_generic
    from mcp_server.core.ast_extractors_extra import (
        extract_swift_imports,
        extract_swift_definitions,
    )

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
    from mcp_server.core.ast_extractors import extract_calls_generic
    from mcp_server.core.ast_extractors_extra import (
        extract_rust_imports,
        extract_rust_definitions,
    )

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
}
