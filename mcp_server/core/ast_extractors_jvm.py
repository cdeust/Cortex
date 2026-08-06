"""Tree-sitter extractors for JVM languages: Java and Kotlin.

Node-type names verified empirically against tree-sitter-language-pack
grammars (java, kotlin). Split from ast_extractors.py to stay under 300
lines.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp_server.core.ast_extractors import _find_children, _text, _walk_type
from mcp_server.core.codebase_parser import ImportInfo, SymbolDef

if TYPE_CHECKING:
    from tree_sitter import Node


# ── Java ────────────────────────────────────────────────────────────────────


def extract_java_imports(root: Node, source: bytes) -> list[ImportInfo]:
    """Extract Java import declarations."""
    imports: list[ImportInfo] = []
    for node in _find_children(root, "import_declaration"):
        mod = _text(node, source).replace("import", "", 1).replace("static", "", 1)
        imports.append(ImportInfo(module=mod.strip().rstrip(";").strip()))
    return imports


_JAVA_TYPE_KINDS = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "enum_declaration": "enum",
    "record_declaration": "class",
}


def extract_java_definitions(root: Node, source: bytes) -> list[SymbolDef]:
    """Extract Java class, interface, enum, record, and method definitions."""
    defs: list[SymbolDef] = []
    _walk_java(root, source, defs, "")
    return defs


def _walk_java(node: Node, source: bytes, defs: list[SymbolDef], parent: str) -> None:
    """Extract Java definitions, qualifying methods by class.

    Iterative (see `ast_extractors._walk_type`): the recursive form spent one
    Python frame per AST level and raised an uncaught RecursionError on deeply
    nested sources. Descendants are pushed reversed, so they pop before the
    remaining siblings and `defs` keeps its depth-first pre-order.
    """
    stack: list[tuple[Node, str]] = [(node, parent)]
    while stack:
        current, scope = stack.pop()
        if current.type in _JAVA_TYPE_KINDS:
            name = current.child_by_field_name("name")
            if name:
                n = _text(name, source)
                defs.append(SymbolDef(name=n, kind=_JAVA_TYPE_KINDS[current.type]))
                body = current.child_by_field_name("body")
                if body:
                    stack.extend((c, n) for c in reversed(body.children))
                continue
            # Unnamed: fall through, exactly as the recursive form did — its
            # `return` sat inside `if name:`.
        if current.type in ("method_declaration", "constructor_declaration"):
            name = current.child_by_field_name("name")
            if name:
                n = _text(name, source)
                full = f"{scope}.{n}" if scope else n
                defs.append(
                    SymbolDef(name=full, kind="method" if scope else "function")
                )
            continue
        stack.extend((c, scope) for c in reversed(current.children))


# ── Kotlin ──────────────────────────────────────────────────────────────────


def extract_kotlin_imports(root: Node, source: bytes) -> list[ImportInfo]:
    """Extract Kotlin import headers."""
    imports: list[ImportInfo] = []
    for header in _walk_type(root, "import_header"):
        ident = _find_children(header, "identifier")
        if ident:
            imports.append(ImportInfo(module=_text(ident[0], source).strip()))
    return imports


def extract_kotlin_definitions(root: Node, source: bytes) -> list[SymbolDef]:
    """Extract Kotlin class, object, interface, and function definitions."""
    defs: list[SymbolDef] = []
    _walk_kotlin(root, source, defs, "")
    return defs


def _walk_kotlin(node: Node, source: bytes, defs: list[SymbolDef], parent: str) -> None:
    """Extract Kotlin definitions, qualifying members by type.

    Iterative for the same reason as `_walk_java`; traversal order preserved.
    """
    stack: list[tuple[Node, str]] = [(node, parent)]
    while stack:
        current, scope = stack.pop()
        if current.type in ("class_declaration", "object_declaration"):
            ident = _find_children(current, "type_identifier")
            if ident:
                n = _text(ident[0], source)
                is_iface = any(c.type == "interface" for c in current.children)
                defs.append(
                    SymbolDef(name=n, kind="interface" if is_iface else "class")
                )
                members = [
                    (member, n)
                    for child in current.children
                    if child.type == "class_body"
                    for member in child.children
                ]
                stack.extend(reversed(members))
                continue
            # Unnamed: fall through, as the recursive form did.
        if current.type == "function_declaration":
            ident = _find_children(current, "simple_identifier")
            if ident:
                n = _text(ident[0], source)
                full = f"{scope}.{n}" if scope else n
                defs.append(
                    SymbolDef(name=full, kind="method" if scope else "function")
                )
            continue
        stack.extend((c, scope) for c in reversed(current.children))
