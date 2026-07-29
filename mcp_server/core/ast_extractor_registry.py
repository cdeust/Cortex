"""Registry for the extra-language tree-sitter extractors.

Builds the (imports, definitions, calls) extractor callables for the JVM,
C-family, and scripting language groups and merges them into one dict for
ast_parser._EXTRACTORS. Split out so ast_parser.py stays under 300 lines.

Pure business logic — no I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from mcp_server.core.codebase_parser import ImportInfo, SymbolDef
from mcp_server.core.ast_extractors import extract_calls_generic
from mcp_server.core.ast_extractors_clike import (
    extract_c_definitions,
    extract_c_imports,
    extract_cpp_definitions,
    extract_csharp_definitions,
    extract_csharp_imports,
)
from mcp_server.core.ast_extractors_jvm import (
    extract_java_definitions,
    extract_java_imports,
    extract_kotlin_definitions,
    extract_kotlin_imports,
)
from mcp_server.core.ast_extractors_scripting import (
    extract_php_definitions,
    extract_php_imports,
    extract_ruby_definitions,
    extract_ruby_imports,
)

if TYPE_CHECKING:
    from tree_sitter import Node
    from tree_sitter_language_pack import SupportedLanguage

Extractor = Callable[
    ["Node", bytes], tuple[list[ImportInfo], list[SymbolDef], list[str]]
]


def _make_extractor(
    imports_fn: Callable[["Node", bytes], list[ImportInfo]],
    defs_fn: Callable[["Node", bytes], list[SymbolDef]],
) -> Extractor:
    """Compose an extractor from an imports fn, a defs fn, and generic calls."""

    def _extract(
        root: Node,
        source: bytes,
    ) -> tuple[list[ImportInfo], list[SymbolDef], list[str]]:

        return (
            imports_fn(root, source),
            defs_fn(root, source),
            extract_calls_generic(root, source),
        )

    return _extract


def build_extra_extractors() -> dict[SupportedLanguage, Extractor]:
    """Build the JVM + C-family + scripting extractor dispatch table.

    Keyed by the language pack's `SupportedLanguage` literal so the type
    checker verifies each grammar name against the pack the environment
    resolved — see the table in `ast_parser._EXTRACTORS` this merges into.
    """

    return {
        "java": _make_extractor(extract_java_imports, extract_java_definitions),
        "kotlin": _make_extractor(extract_kotlin_imports, extract_kotlin_definitions),
        "c": _make_extractor(extract_c_imports, extract_c_definitions),
        "cpp": _make_extractor(extract_c_imports, extract_cpp_definitions),
        "csharp": _make_extractor(extract_csharp_imports, extract_csharp_definitions),
        "ruby": _make_extractor(extract_ruby_imports, extract_ruby_definitions),
        "php": _make_extractor(extract_php_imports, extract_php_definitions),
    }
