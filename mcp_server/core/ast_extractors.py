"""Tree-sitter AST extractors for Python and JavaScript/TypeScript.

Additional languages (Go, Swift, Rust) in ast_extractors_extra.py.
Also provides the generic call-site extractor used by all languages.

Pure functions — no I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp_server.core.codebase_parser import ImportInfo, SymbolDef

if TYPE_CHECKING:
    from tree_sitter import Node


def _text(node: Node, source: bytes) -> str:
    """Get node text."""
    return source[node.start_byte:node.end_byte].decode(errors="replace")


def _find_children(node: Node, *types: str) -> list[Node]:
    """Find all direct children matching given types."""
    return [c for c in node.children if c.type in types]


def _walk_type(node: Node, node_type: str) -> list[Node]:
    """Recursively find all descendants of a given type."""
    results: list[Node] = []
    if node.type == node_type:
        results.append(node)
    for child in node.children:
        results.extend(_walk_type(child, node_type))
    return results


# ── Python ────────────────────────────────────────────────────────────────


def extract_python_imports(root: Node, source: bytes) -> list[ImportInfo]:
    """Extract Python import and from...import statements."""
    imports: list[ImportInfo] = []
    for node in root.children:
        if node.type == "import_statement":
            for name_node in _find_children(node, "dotted_name"):
                imports.append(ImportInfo(module=_text(name_node, source)))
        elif node.type == "import_from_statement":
            mod_node = node.child_by_field_name("module_name")
            module = _text(mod_node, source) if mod_node else ""
            names = [
                _text(n, source)
                for n in _find_children(node, "dotted_name", "aliased_import")
                if n != mod_node
            ]
            is_rel = module.startswith(".")
            imports.append(ImportInfo(module=module, names=names, is_relative=is_rel))
    return imports


def extract_python_definitions(
    root: Node, source: bytes, parent_class: str = "",
) -> list[SymbolDef]:
    """Extract Python def/class with class-method binding."""
    defs: list[SymbolDef] = []
    for node in root.children:
        if node.type == "function_definition":
            _extract_python_func(node, source, defs, parent_class)
        elif node.type == "decorated_definition":
            _extract_python_decorated(node, source, defs, parent_class)
        elif node.type == "class_definition":
            _extract_python_class(node, source, defs)
    return defs


def _extract_python_func(
    node: Node, source: bytes, defs: list[SymbolDef], parent: str,
) -> None:
    """Extract a single Python function definition."""
    name_node = node.child_by_field_name("name")
    params_node = node.child_by_field_name("parameters")
    name = _text(name_node, source) if name_node else ""
    sig = _text(params_node, source)[:120] if params_node else ""
    kind = "method" if parent else "function"
    full_name = f"{parent}.{name}" if parent else name
    defs.append(SymbolDef(name=full_name, kind=kind, signature=sig))


def _extract_python_decorated(
    node: Node, source: bytes, defs: list[SymbolDef], parent: str,
) -> None:
    """Extract definitions from decorated blocks."""
    for child in node.children:
        if child.type in ("function_definition", "class_definition"):
            fake = type("N", (), {"children": [child]})()
            defs.extend(extract_python_definitions(fake, source, parent))


def _extract_python_class(
    node: Node, source: bytes, defs: list[SymbolDef],
) -> None:
    """Extract a class and recurse into its body for methods."""
    name_node = node.child_by_field_name("name")
    superclass_node = node.child_by_field_name("superclasses")
    cls_name = _text(name_node, source) if name_node else ""
    sig = _text(superclass_node, source)[:120] if superclass_node else ""
    defs.append(SymbolDef(name=cls_name, kind="class", signature=sig))
    body = node.child_by_field_name("body")
    if body:
        defs.extend(extract_python_definitions(body, source, cls_name))


# ── JavaScript / TypeScript ───────────────────────────────────────────────


def extract_js_imports(root: Node, source: bytes) -> list[ImportInfo]:
    """Extract JS/TS import statements."""
    imports: list[ImportInfo] = []
    for node in _walk_type(root, "import_statement"):
        src = node.child_by_field_name("source")
        if src:
            mod = _text(src, source).strip("'\"")
            imports.append(ImportInfo(module=mod, is_relative=mod.startswith(".")))
    return imports


def extract_js_definitions(root: Node, source: bytes) -> list[SymbolDef]:
    """Extract JS/TS function, class, interface, type definitions."""
    defs: list[SymbolDef] = []
    for node in root.children:
        _extract_js_node(node, source, defs, "")
    return defs


def _extract_js_node(
    node: Node, source: bytes, defs: list[SymbolDef], parent: str,
) -> None:
    """Recursively extract JS definitions with scope tracking."""
    if node.type in ("function_declaration", "function"):
        _extract_js_func(node, source, defs, parent)
    elif node.type == "class_declaration":
        _extract_js_class(node, source, defs)
    elif node.type == "interface_declaration":
        name = node.child_by_field_name("name")
        if name:
            defs.append(SymbolDef(name=_text(name, source), kind="interface"))
    elif node.type == "type_alias_declaration":
        name = node.child_by_field_name("name")
        if name:
            defs.append(SymbolDef(name=_text(name, source), kind="type"))
    elif node.type == "export_statement":
        for child in node.children:
            _extract_js_node(child, source, defs, parent)
    elif node.type == "method_definition":
        name = node.child_by_field_name("name")
        if name:
            full = f"{parent}.{_text(name, source)}" if parent else _text(name, source)
            defs.append(SymbolDef(name=full, kind="method"))


def _extract_js_func(
    node: Node, source: bytes, defs: list[SymbolDef], parent: str,
) -> None:
    """Extract a JS function declaration."""
    name_node = node.child_by_field_name("name")
    params = node.child_by_field_name("parameters")
    if name_node:
        name = _text(name_node, source)
        full = f"{parent}.{name}" if parent else name
        sig = _text(params, source)[:120] if params else ""
        defs.append(SymbolDef(name=full, kind="function", signature=sig))


def _extract_js_class(
    node: Node, source: bytes, defs: list[SymbolDef],
) -> None:
    """Extract a JS class and recurse for methods."""
    name_node = node.child_by_field_name("name")
    if not name_node:
        return
    cls_name = _text(name_node, source)
    defs.append(SymbolDef(name=cls_name, kind="class"))
    body = node.child_by_field_name("body")
    if body:
        for child in body.children:
            _extract_js_node(child, source, defs, cls_name)


# ── Generic call extraction ──────────────────────────────────────────────


def extract_calls_generic(root: Node, source: bytes) -> list[str]:
    """Extract all function/method call names from AST."""
    calls: list[str] = []
    seen: set[str] = set()
    for call_type in ("call", "call_expression"):
        for node in _walk_type(root, call_type):
            func = node.child_by_field_name("function")
            if not func:
                continue
            name = _text(func, source).strip()
            if name and name not in seen and len(name) < 100:
                calls.append(name)
                seen.add(name)
    return calls
