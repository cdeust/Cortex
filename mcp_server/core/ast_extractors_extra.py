"""Tree-sitter extractors for Go, Swift, and Rust.

Split from ast_extractors.py to stay under 300 lines.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp_server.core.codebase_parser import ImportInfo, SymbolDef
from mcp_server.core.ast_extractors import _text, _walk_type, _find_children

if TYPE_CHECKING:
    from tree_sitter import Node


# ── Go ────────────────────────────────────────────────────────────────────


def extract_go_imports(root: Node, source: bytes) -> list[ImportInfo]:
    """Extract Go import statements."""
    imports: list[ImportInfo] = []
    for node in _walk_type(root, "import_spec"):
        path_node = node.child_by_field_name("path")
        if path_node:
            mod = _text(path_node, source).strip('"')
            imports.append(ImportInfo(module=mod))
    return imports


def extract_go_definitions(root: Node, source: bytes) -> list[SymbolDef]:
    """Extract Go func, type, and method definitions."""
    defs: list[SymbolDef] = []
    for node in root.children:
        if node.type == "function_declaration":
            name = node.child_by_field_name("name")
            params = node.child_by_field_name("parameters")
            if name:
                sig = _text(params, source)[:120] if params else ""
                defs.append(SymbolDef(
                    name=_text(name, source), kind="function", signature=sig,
                ))
        elif node.type == "method_declaration":
            name = node.child_by_field_name("name")
            receiver = node.child_by_field_name("receiver")
            if name:
                recv = _extract_go_receiver(receiver, source)
                full = f"{recv}.{_text(name, source)}" if recv else _text(name, source)
                defs.append(SymbolDef(name=full, kind="method"))
        elif node.type == "type_declaration":
            for spec in _find_children(node, "type_spec"):
                n = spec.child_by_field_name("name")
                t = spec.child_by_field_name("type")
                if n:
                    kind = t.type.replace("_type", "") if t and t.type in (
                        "struct_type", "interface_type",
                    ) else "type"
                    defs.append(SymbolDef(name=_text(n, source), kind=kind))
    return defs


def _extract_go_receiver(receiver: Node | None, source: bytes) -> str:
    """Extract Go method receiver type name."""
    if not receiver:
        return ""
    for child in _walk_type(receiver, "type_identifier"):
        return _text(child, source)
    return ""


# ── Swift ─────────────────────────────────────────────────────────────────


def extract_swift_imports(root: Node, source: bytes) -> list[ImportInfo]:
    """Extract Swift import statements."""
    return [
        ImportInfo(module=_text(n, source).replace("import ", "").strip())
        for n in _walk_type(root, "import_declaration")
    ]


def extract_swift_definitions(root: Node, source: bytes) -> list[SymbolDef]:
    """Extract Swift func, class, struct, protocol, enum definitions."""
    defs: list[SymbolDef] = []
    _extract_swift_node(root, source, defs, "")
    return defs


_SWIFT_KIND_MAP = {
    "class_declaration": "class",
    "struct_declaration": "class",
    "protocol_declaration": "protocol",
    "enum_declaration": "enum",
}


def _extract_swift_node(
    node: Node, source: bytes, defs: list[SymbolDef], parent: str,
) -> None:
    """Recursively extract Swift definitions."""
    if node.type == "function_declaration":
        name = node.child_by_field_name("name")
        if name:
            n = _text(name, source)
            full = f"{parent}.{n}" if parent else n
            defs.append(SymbolDef(name=full, kind="method" if parent else "function"))
    elif node.type in _SWIFT_KIND_MAP:
        name = node.child_by_field_name("name")
        if name:
            n = _text(name, source)
            defs.append(SymbolDef(name=n, kind=_SWIFT_KIND_MAP[node.type]))
            body = node.child_by_field_name("body")
            if body:
                for child in body.children:
                    _extract_swift_node(child, source, defs, n)
    else:
        for child in node.children:
            _extract_swift_node(child, source, defs, parent)


# ── Rust ──────────────────────────────────────────────────────────────────


def extract_rust_imports(root: Node, source: bytes) -> list[ImportInfo]:
    """Extract Rust use statements."""
    return [
        ImportInfo(module=_text(n, source).replace("use ", "").rstrip(";").strip())
        for n in _walk_type(root, "use_declaration")
    ]


def extract_rust_definitions(root: Node, source: bytes) -> list[SymbolDef]:
    """Extract Rust fn, struct, enum, trait, impl definitions."""
    defs: list[SymbolDef] = []
    for node in root.children:
        _extract_rust_node(node, source, defs)
    return defs


def _extract_rust_node(
    node: Node, source: bytes, defs: list[SymbolDef],
) -> None:
    """Extract a single Rust top-level item."""
    if node.type == "function_item":
        name = node.child_by_field_name("name")
        if name:
            defs.append(SymbolDef(name=_text(name, source), kind="function"))
    elif node.type == "struct_item":
        name = node.child_by_field_name("name")
        if name:
            defs.append(SymbolDef(name=_text(name, source), kind="class"))
    elif node.type == "enum_item":
        name = node.child_by_field_name("name")
        if name:
            defs.append(SymbolDef(name=_text(name, source), kind="enum"))
    elif node.type == "trait_item":
        name = node.child_by_field_name("name")
        if name:
            defs.append(SymbolDef(name=_text(name, source), kind="trait"))
    elif node.type == "impl_item":
        _extract_rust_impl(node, source, defs)


def _extract_rust_impl(
    node: Node, source: bytes, defs: list[SymbolDef],
) -> None:
    """Extract methods from a Rust impl block."""
    type_node = node.child_by_field_name("type")
    if not type_node:
        return
    impl_name = _text(type_node, source)
    body = node.child_by_field_name("body")
    if not body:
        return
    for child in body.children:
        if child.type == "function_item":
            fn_name = child.child_by_field_name("name")
            if fn_name:
                full = f"{impl_name}.{_text(fn_name, source)}"
                defs.append(SymbolDef(name=full, kind="method"))
