"""Codebase parser — regex-based source file analysis.

Extracts imports, type definitions, function definitions, and module
structure from source files. No AST parsing — pure regex heuristics
that work across Python, TypeScript, Go, Rust, Swift, and more.

Pure business logic — no I/O. Callers pass file content as strings.
Language-specific extractors live in codebase_extractors.py.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass(slots=True)
class ImportInfo:
    """A single import statement."""

    module: str
    names: list[str] = field(default_factory=list)
    is_relative: bool = False


@dataclass(slots=True)
class SymbolDef:
    """A symbol definition (function, class, type, constant)."""

    name: str
    kind: str  # function, class, interface, type, constant, protocol, trait, enum
    signature: str = ""
    docstring: str = ""


@dataclass(slots=True)
class FileAnalysis:
    """Complete analysis of a single source file."""

    path: str
    language: str
    content_hash: str
    imports: list[ImportInfo] = field(default_factory=list)
    definitions: list[SymbolDef] = field(default_factory=list)
    docstring: str = ""
    line_count: int = 0


# ── Language detection ────────────────────────────────────────────────────

EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".swift": "swift",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".cs": "csharp",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".m": "objc",
}


def detect_language(path: str) -> str:
    """Detect language from file extension."""
    for ext, lang in EXT_TO_LANG.items():
        if path.endswith(ext):
            return lang
    return "unknown"


def parse_file(path: str, content: str) -> FileAnalysis:
    """Parse a source file and extract its structure.

    Args:
        path: Relative file path.
        content: Full file content as string.

    Returns:
        FileAnalysis with imports, definitions, docstring, and content hash.
    """
    from mcp_server.core.codebase_extractors import (
        IMPORT_EXTRACTORS,
        SYMBOL_EXTRACTORS,
        extract_docstring,
    )

    language = detect_language(path)
    content_hash = hashlib.sha256(content.encode(errors="replace")).hexdigest()[:16]

    imports = IMPORT_EXTRACTORS.get(language, lambda _: [])(content)
    definitions = SYMBOL_EXTRACTORS.get(language, lambda _: [])(content)
    docstring = extract_docstring(content, language)

    return FileAnalysis(
        path=path,
        language=language,
        content_hash=content_hash,
        imports=imports,
        definitions=definitions,
        docstring=docstring,
        line_count=content.count("\n") + 1,
    )


def build_memory_content(analysis: FileAnalysis) -> str:
    """Build structured memory content from a file analysis.

    Format designed for good embeddings — includes file path, language,
    imports, definitions, and purpose in a human-readable format.

    Args:
        analysis: Parsed file analysis.

    Returns:
        Structured memory content string.
    """
    parts = [f"# File: {analysis.path}", f"Language: {analysis.language}"]

    if analysis.docstring:
        parts.append(f"Purpose: {analysis.docstring}")

    if analysis.imports:
        parts.append("")
        parts.append("## Imports")
        for imp in analysis.imports[:20]:
            if imp.names:
                parts.append(f"- from {imp.module} import {', '.join(imp.names[:5])}")
            else:
                parts.append(f"- {imp.module}")

    if analysis.definitions:
        parts.append("")
        parts.append("## Definitions")
        for sym in analysis.definitions[:30]:
            sig = f"({sym.signature})" if sym.signature else ""
            parts.append(f"- {sym.kind}: {sym.name}{sig}")

    parts.append(f"\n{analysis.line_count} lines")
    return "\n".join(parts)
