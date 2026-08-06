"""Tree-sitter extractors for scripting languages: Ruby and PHP.

Node-type names verified empirically against tree-sitter-language-pack
grammars (ruby, php). Ruby imports are ``require``/``require_relative``
call sites; PHP imports are ``namespace_use_clause`` nodes.

Split from ast_extractors.py to stay under 300 lines.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp_server.core.ast_extractors import _find_children, _text, _walk_type
from mcp_server.core.codebase_parser import ImportInfo, SymbolDef

if TYPE_CHECKING:
    from tree_sitter import Node


# ── Ruby ──────────────────────────────────────────────────────────────────────

_RUBY_REQUIRE = {"require", "require_relative", "load"}


def extract_ruby_imports(root: Node, source: bytes) -> list[ImportInfo]:
    """Extract Ruby require/require_relative/load call sites."""
    imports: list[ImportInfo] = []
    for call in _walk_type(root, "call"):
        method = call.child_by_field_name("method")
        if not method or _text(method, source) not in _RUBY_REQUIRE:
            continue
        args = call.child_by_field_name("arguments")
        if args:
            mod = _text(args, source).strip().strip("()").strip().strip("\"'")
            if mod:
                imports.append(ImportInfo(module=mod))
    return imports


_RUBY_KINDS = {"class": "class", "module": "module"}


def extract_ruby_definitions(root: Node, source: bytes) -> list[SymbolDef]:
    """Extract Ruby class, module, and method definitions."""
    defs: list[SymbolDef] = []
    _walk_ruby(root, source, defs, "")
    return defs


def _walk_ruby(node: Node, source: bytes, defs: list[SymbolDef], parent: str) -> None:
    """Extract Ruby definitions, qualifying methods by class.

    Iterative (see `ast_extractors._walk_type`): one Python frame per AST level
    raised an uncaught RecursionError on deeply nested sources. Descendants are
    pushed reversed, so `defs` keeps its depth-first pre-order.
    """
    stack: list[tuple[Node, str]] = [(node, parent)]
    while stack:
        current, scope = stack.pop()
        if current.type in _RUBY_KINDS:
            name = current.child_by_field_name("name")
            if name:
                n = _text(name, source)
                defs.append(SymbolDef(name=n, kind=_RUBY_KINDS[current.type]))
                stack.extend((c, n) for c in reversed(current.children))
                continue
            # Unnamed: fall through, as the recursive form did.
        if current.type == "method":
            name = current.child_by_field_name("name")
            if name:
                n = _text(name, source)
                full = f"{scope}.{n}" if scope else n
                defs.append(
                    SymbolDef(name=full, kind="method" if scope else "function")
                )
            continue
        stack.extend((c, scope) for c in reversed(current.children))


# ── PHP ───────────────────────────────────────────────────────────────────────


def extract_php_imports(root: Node, source: bytes) -> list[ImportInfo]:
    """Extract PHP `use` namespace import clauses."""
    imports: list[ImportInfo] = []
    for clause in _walk_type(root, "namespace_use_clause"):
        mod = _text(clause, source).strip().rstrip(";").strip()
        if mod:
            imports.append(ImportInfo(module=mod))
    return imports


_PHP_KINDS = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "trait_declaration": "trait",
    "enum_declaration": "enum",
}


def extract_php_definitions(root: Node, source: bytes) -> list[SymbolDef]:
    """Extract PHP class, interface, trait, function, and method definitions."""
    defs: list[SymbolDef] = []
    _walk_php(root, source, defs, "")
    return defs


def _walk_php(node: Node, source: bytes, defs: list[SymbolDef], parent: str) -> None:
    """Extract PHP definitions, qualifying methods by type.

    Iterative for the same reason as `_walk_ruby`; traversal order preserved.
    """
    stack: list[tuple[Node, str]] = [(node, parent)]
    while stack:
        current, scope = stack.pop()
        if current.type in _PHP_KINDS:
            name = current.child_by_field_name("name")
            if name:
                n = _text(name, source)
                defs.append(SymbolDef(name=n, kind=_PHP_KINDS[current.type]))
                members = [
                    (member, n)
                    for child in _find_children(current, "declaration_list")
                    for member in child.children
                ]
                stack.extend(reversed(members))
                continue
            # Unnamed: fall through, as the recursive form did.
        if current.type in ("function_definition", "method_declaration"):
            name = current.child_by_field_name("name")
            if name:
                n = _text(name, source)
                full = f"{scope}.{n}" if scope else n
                defs.append(
                    SymbolDef(name=full, kind="method" if scope else "function")
                )
            continue
        stack.extend((c, scope) for c in reversed(current.children))
