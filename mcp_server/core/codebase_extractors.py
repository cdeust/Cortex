"""Per-language import and symbol extractors for codebase analysis.

Regex-based heuristics for Python, TypeScript/JavaScript, Go, Rust,
and Swift. No AST parsing — works on raw text.

Pure functions — no I/O, no state.
"""

from __future__ import annotations

import re
from typing import Callable

from mcp_server.core.codebase_parser import ImportInfo, SymbolDef

# ── Import patterns ───────────────────────────────────────────────────────

_PY_IMPORT = re.compile(r"^import\s+([\w.]+)", re.MULTILINE)
_PY_FROM_IMPORT = re.compile(r"^from\s+([\w.]+)\s+import\s+(.+?)$", re.MULTILINE)
_JS_IMPORT = re.compile(
    r"""^import\s+(?:\{[^}]*\}|[\w*]+(?:\s+as\s+\w+)?)\s+from\s+['"]([^'"]+)['"]""",
    re.MULTILINE,
)
_JS_REQUIRE = re.compile(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""")
_GO_IMPORT_SINGLE = re.compile(r'^import\s+"([^"]+)"', re.MULTILINE)
_GO_IMPORT_BLOCK = re.compile(r"^import\s*\((.*?)\)", re.MULTILINE | re.DOTALL)
_GO_IMPORT_LINE = re.compile(r'"([^"]+)"')
_RUST_USE = re.compile(r"^use\s+([\w:]+(?:::\{[^}]+\})?)", re.MULTILINE)
_SWIFT_IMPORT = re.compile(r"^import\s+(\w+)", re.MULTILINE)

# ── Symbol patterns ───────────────────────────────────────────────────────

_PY_DEF = re.compile(r"^(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)", re.MULTILINE)
_PY_CLASS = re.compile(r"^class\s+(\w+)(?:\(([^)]*)\))?", re.MULTILINE)

_JS_FUNC = re.compile(
    r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)", re.MULTILINE
)
_JS_CLASS = re.compile(
    r"^(?:export\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?", re.MULTILINE
)
_JS_INTERFACE = re.compile(r"^(?:export\s+)?interface\s+(\w+)", re.MULTILINE)
_JS_TYPE = re.compile(r"^(?:export\s+)?type\s+(\w+)\s*=", re.MULTILINE)

_GO_FUNC = re.compile(r"^func\s+(?:\([^)]*\)\s+)?(\w+)\s*\(([^)]*)\)", re.MULTILINE)
_GO_TYPE = re.compile(r"^type\s+(\w+)\s+(struct|interface)\b", re.MULTILINE)

_RUST_FN = re.compile(
    r"^(?:pub\s+)?(?:async\s+)?fn\s+(\w+)\s*(?:<[^>]*>)?\s*\(([^)]*)\)", re.MULTILINE
)
_RUST_STRUCT = re.compile(r"^(?:pub\s+)?struct\s+(\w+)", re.MULTILINE)
_RUST_ENUM = re.compile(r"^(?:pub\s+)?enum\s+(\w+)", re.MULTILINE)
_RUST_TRAIT = re.compile(r"^(?:pub\s+)?trait\s+(\w+)", re.MULTILINE)

_SWIFT_FUNC = re.compile(
    r"^\s*(?:public\s+|private\s+|internal\s+|open\s+|static\s+)*"
    r"func\s+(\w+)\s*\(([^)]*)\)",
    re.MULTILINE,
)
_SWIFT_CLASS = re.compile(
    r"^\s*(?:public\s+|private\s+|open\s+|final\s+)*class\s+(\w+)", re.MULTILINE
)
_SWIFT_STRUCT = re.compile(r"^\s*(?:public\s+|private\s+)*struct\s+(\w+)", re.MULTILINE)
_SWIFT_PROTOCOL = re.compile(
    r"^\s*(?:public\s+|private\s+)*protocol\s+(\w+)", re.MULTILINE
)
_SWIFT_ENUM = re.compile(r"^\s*(?:public\s+|private\s+)*enum\s+(\w+)", re.MULTILINE)

# ── Docstring patterns ────────────────────────────────────────────────────

_PY_MODULE_DOC = re.compile(r'^(?:"""(.*?)"""|\'\'\'(.*?)\'\'\')', re.DOTALL)
_JS_MODULE_DOC = re.compile(r"^/\*\*(.*?)\*/", re.DOTALL)


# ── Import extractors ────────────────────────────────────────────────────


def extract_imports_python(content: str) -> list[ImportInfo]:
    """Extract Python import and from...import statements."""
    imports: list[ImportInfo] = []
    for m in _PY_IMPORT.finditer(content):
        imports.append(ImportInfo(module=m.group(1)))
    for m in _PY_FROM_IMPORT.finditer(content):
        module = m.group(1)
        names = [n.strip() for n in m.group(2).split(",")]
        imports.append(
            ImportInfo(module=module, names=names, is_relative=module.startswith("."))
        )
    return imports


def extract_imports_js(content: str) -> list[ImportInfo]:
    """Extract JS/TS import and require statements."""
    imports: list[ImportInfo] = []
    for m in _JS_IMPORT.finditer(content):
        mod = m.group(1)
        imports.append(ImportInfo(module=mod, is_relative=mod.startswith(".")))
    for m in _JS_REQUIRE.finditer(content):
        mod = m.group(1)
        imports.append(ImportInfo(module=mod, is_relative=mod.startswith(".")))
    return imports


def extract_imports_go(content: str) -> list[ImportInfo]:
    """Extract Go single and block imports."""
    imports: list[ImportInfo] = []
    for m in _GO_IMPORT_SINGLE.finditer(content):
        imports.append(ImportInfo(module=m.group(1)))
    for m in _GO_IMPORT_BLOCK.finditer(content):
        for line_m in _GO_IMPORT_LINE.finditer(m.group(1)):
            imports.append(ImportInfo(module=line_m.group(1)))
    return imports


def extract_imports_rust(content: str) -> list[ImportInfo]:
    """Extract Rust use statements."""
    return [ImportInfo(module=m.group(1)) for m in _RUST_USE.finditer(content)]


def extract_imports_swift(content: str) -> list[ImportInfo]:
    """Extract Swift import statements."""
    return [ImportInfo(module=m.group(1)) for m in _SWIFT_IMPORT.finditer(content)]


# ── Symbol extractors ─────────────────────────────────────────────────────


def extract_symbols_python(content: str) -> list[SymbolDef]:
    """Extract Python def and class definitions."""
    defs: list[SymbolDef] = []
    for m in _PY_DEF.finditer(content):
        defs.append(
            SymbolDef(name=m.group(1), kind="function", signature=m.group(2)[:120])
        )
    for m in _PY_CLASS.finditer(content):
        defs.append(
            SymbolDef(name=m.group(1), kind="class", signature=m.group(2) or "")
        )
    return defs


def extract_symbols_js(content: str) -> list[SymbolDef]:
    """Extract JS/TS function, class, interface, and type definitions."""
    defs: list[SymbolDef] = []
    for m in _JS_FUNC.finditer(content):
        defs.append(
            SymbolDef(name=m.group(1), kind="function", signature=m.group(2)[:120])
        )
    for m in _JS_CLASS.finditer(content):
        defs.append(
            SymbolDef(name=m.group(1), kind="class", signature=m.group(2) or "")
        )
    for m in _JS_INTERFACE.finditer(content):
        defs.append(SymbolDef(name=m.group(1), kind="interface"))
    for m in _JS_TYPE.finditer(content):
        defs.append(SymbolDef(name=m.group(1), kind="type"))
    return defs


def extract_symbols_go(content: str) -> list[SymbolDef]:
    """Extract Go func and type definitions."""
    defs: list[SymbolDef] = []
    for m in _GO_FUNC.finditer(content):
        defs.append(
            SymbolDef(name=m.group(1), kind="function", signature=m.group(2)[:120])
        )
    for m in _GO_TYPE.finditer(content):
        defs.append(SymbolDef(name=m.group(1), kind=m.group(2)))
    return defs


def extract_symbols_rust(content: str) -> list[SymbolDef]:
    """Extract Rust fn, struct, enum, and trait definitions."""
    defs: list[SymbolDef] = []
    for m in _RUST_FN.finditer(content):
        defs.append(
            SymbolDef(name=m.group(1), kind="function", signature=m.group(2)[:120])
        )
    for m in _RUST_STRUCT.finditer(content):
        defs.append(SymbolDef(name=m.group(1), kind="class"))
    for m in _RUST_ENUM.finditer(content):
        defs.append(SymbolDef(name=m.group(1), kind="enum"))
    for m in _RUST_TRAIT.finditer(content):
        defs.append(SymbolDef(name=m.group(1), kind="trait"))
    return defs


def extract_symbols_swift(content: str) -> list[SymbolDef]:
    """Extract Swift func, class, struct, protocol, and enum definitions."""
    defs: list[SymbolDef] = []
    for m in _SWIFT_FUNC.finditer(content):
        defs.append(
            SymbolDef(name=m.group(1), kind="function", signature=m.group(2)[:120])
        )
    for m in _SWIFT_CLASS.finditer(content):
        defs.append(SymbolDef(name=m.group(1), kind="class"))
    for m in _SWIFT_STRUCT.finditer(content):
        defs.append(SymbolDef(name=m.group(1), kind="class"))
    for m in _SWIFT_PROTOCOL.finditer(content):
        defs.append(SymbolDef(name=m.group(1), kind="protocol"))
    for m in _SWIFT_ENUM.finditer(content):
        defs.append(SymbolDef(name=m.group(1), kind="enum"))
    return defs


def extract_docstring(content: str, language: str) -> str:
    """Extract the module-level docstring (first comment block)."""
    if language == "python":
        m = _PY_MODULE_DOC.match(content)
        if m:
            return (m.group(1) or m.group(2) or "").strip()[:200]
    elif language in ("javascript", "typescript"):
        m = _JS_MODULE_DOC.match(content)
        if m:
            text = m.group(1).strip()
            text = re.sub(r"^\s*\*\s?", "", text, flags=re.MULTILINE)
            return text.strip()[:200]
    for line in content.split("\n")[:5]:
        stripped = line.strip()
        if stripped.startswith("#") and not stripped.startswith("#!"):
            return stripped.lstrip("# ").strip()[:200]
        if stripped.startswith("//"):
            return stripped.lstrip("/ ").strip()[:200]
    return ""


# ── Registry maps ─────────────────────────────────────────────────────────

IMPORT_EXTRACTORS: dict[str, Callable[[str], list[ImportInfo]]] = {
    "python": extract_imports_python,
    "javascript": extract_imports_js,
    "typescript": extract_imports_js,
    "go": extract_imports_go,
    "rust": extract_imports_rust,
    "swift": extract_imports_swift,
}

SYMBOL_EXTRACTORS: dict[str, Callable[[str], list[SymbolDef]]] = {
    "python": extract_symbols_python,
    "javascript": extract_symbols_js,
    "typescript": extract_symbols_js,
    "go": extract_symbols_go,
    "rust": extract_symbols_rust,
    "swift": extract_symbols_swift,
}
