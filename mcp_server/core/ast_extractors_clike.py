"""Tree-sitter extractors for C-family languages: C, C++, and C#.

Node-type names verified empirically against tree-sitter-language-pack
grammars (c, cpp, csharp). C/C++ carry function names inside nested
``function_declarator`` nodes; C# uses ``name`` fields like Java.

Split from ast_extractors.py to stay under 300 lines.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp_server.core.ast_extractors import _find_children, _text, _walk_type
from mcp_server.core.codebase_parser import ImportInfo, SymbolDef

if TYPE_CHECKING:
    from tree_sitter import Node


# ── C ────────────────────────────────────────────────────────────────────────


def extract_c_imports(root: Node, source: bytes) -> list[ImportInfo]:
    """Extract C #include directives."""
    imports: list[ImportInfo] = []
    for node in _walk_type(root, "preproc_include"):
        path = node.child_by_field_name("path")
        if path:
            mod = _text(path, source).strip().strip('"<>')
            imports.append(ImportInfo(module=mod))
    return imports


def _declarator_name(declarator: Node | None, source: bytes) -> str:
    """Unwrap nested C/C++ declarators down to the identifier."""
    node = declarator
    while node is not None:
        if node.type in ("identifier", "field_identifier", "type_identifier"):
            return _text(node, source)
        if node.type in ("qualified_identifier", "destructor_name", "operator_name"):
            return _text(node, source)
        node = node.child_by_field_name("declarator")
    return ""


def extract_c_definitions(root: Node, source: bytes) -> list[SymbolDef]:
    """Extract C function, struct, and typedef definitions."""
    defs: list[SymbolDef] = []
    for node in _walk_type(root, "function_definition"):
        name = _declarator_name(node.child_by_field_name("declarator"), source)
        if name:
            defs.append(SymbolDef(name=name, kind="function"))
    for node in _walk_type(root, "struct_specifier"):
        name = node.child_by_field_name("name")
        if name:
            defs.append(SymbolDef(name=_text(name, source), kind="class"))
    for node in _walk_type(root, "type_definition"):
        decl = node.child_by_field_name("declarator")
        if decl:
            defs.append(SymbolDef(name=_text(decl, source), kind="type"))
    return defs


# ── C++ ──────────────────────────────────────────────────────────────────────


def extract_cpp_definitions(root: Node, source: bytes) -> list[SymbolDef]:
    """Extract C++ class, struct, namespace, and function definitions."""
    defs: list[SymbolDef] = []
    for node in _walk_type(root, "class_specifier"):
        name = node.child_by_field_name("name")
        if name:
            defs.append(SymbolDef(name=_text(name, source), kind="class"))
    for node in _walk_type(root, "namespace_definition"):
        name = node.child_by_field_name("name")
        if name:
            defs.append(SymbolDef(name=_text(name, source), kind="namespace"))
    for node in _walk_type(root, "function_definition"):
        name = _declarator_name(node.child_by_field_name("declarator"), source)
        if name:
            kind = "method" if "::" in name else "function"
            defs.append(SymbolDef(name=name, kind=kind))
    return defs


# ── C# ────────────────────────────────────────────────────────────────────────


def extract_csharp_imports(root: Node, source: bytes) -> list[ImportInfo]:
    """Extract C# using directives."""
    imports: list[ImportInfo] = []
    for node in _walk_type(root, "using_directive"):
        mod = _text(node, source).replace("using", "", 1).strip().rstrip(";").strip()
        if mod:
            imports.append(ImportInfo(module=mod))
    return imports


_CSHARP_TYPE_KINDS = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "enum_declaration": "enum",
    "struct_declaration": "class",
    "record_declaration": "class",
}


def extract_csharp_definitions(root: Node, source: bytes) -> list[SymbolDef]:
    """Extract C# type and method definitions."""
    defs: list[SymbolDef] = []
    _walk_csharp(root, source, defs, "")
    return defs


def _walk_csharp(node: Node, source: bytes, defs: list[SymbolDef], parent: str) -> None:
    """Extract C# definitions, qualifying methods by type.

    Iterative (see `ast_extractors._walk_type`): one Python frame per AST level
    raised an uncaught RecursionError on deeply nested sources. Descendants are
    pushed reversed, so `defs` keeps its depth-first pre-order.
    """
    stack: list[tuple[Node, str]] = [(node, parent)]
    while stack:
        current, scope = stack.pop()
        if current.type in _CSHARP_TYPE_KINDS:
            name = current.child_by_field_name("name")
            if name:
                n = _text(name, source)
                defs.append(SymbolDef(name=n, kind=_CSHARP_TYPE_KINDS[current.type]))
                members = [
                    (member, n)
                    for child in _find_children(current, "declaration_list")
                    for member in child.children
                ]
                stack.extend(reversed(members))
                continue
            # Unnamed: fall through, as the recursive form did.
        if current.type == "method_declaration":
            name = current.child_by_field_name("name")
            if name:
                n = _text(name, source)
                full = f"{scope}.{n}" if scope else n
                defs.append(
                    SymbolDef(name=full, kind="method" if scope else "function")
                )
            continue
        stack.extend((c, scope) for c in reversed(current.children))
