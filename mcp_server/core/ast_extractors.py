"""Tree-sitter AST extractors for Python and JavaScript/TypeScript.

Additional languages (Go, Swift, Rust) in ast_extractors_extra.py.

Pure functions — no I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp_server.core.codebase_parser import ImportInfo, SymbolDef

if TYPE_CHECKING:
    from tree_sitter import Node

# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_MAX_CALL_NAME_LEN = 100  # sanity cap: longer "callee names" are noise


def _text(node: Node, source: bytes) -> str:
    """Get node text."""
    return source[node.start_byte : node.end_byte].decode(errors="replace")


def _find_children(node: Node, *types: str) -> list[Node]:
    """Find all direct children matching given types."""
    return [c for c in node.children if c.type in types]


def _walk_type(node: Node, node_type: str) -> list[Node]:
    """Find `node` and all its descendants of a given type, in document order.

    Iterative on purpose. The recursive form consumed one Python frame per AST
    level and raised RecursionError at an AST depth of ~1003 under the default
    limit of 1000 — reachable on minified or generated sources in third-party
    repositories, and unhandled (no caller catches RecursionError). Heap depth
    replaces stack depth; the traversal order is unchanged.
    """
    results: list[Node] = []
    stack: list[Node] = [node]
    while stack:
        current = stack.pop()
        if current.type == node_type:
            results.append(current)
        # Reversed, so siblings pop left-to-right and the result stays
        # pre-order document order — identical to the recursive form.
        stack.extend(reversed(current.children))
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
    root: Node,
    source: bytes,
    parent_class: str = "",
) -> list[SymbolDef]:
    """Extract Python def/class with class-method binding."""
    return _extract_python_children(root.children, source, parent_class)


def _extract_python_children(
    children: list[Node],
    source: bytes,
    parent_class: str,
) -> list[SymbolDef]:
    """Dispatch definition extraction over a sequence of sibling nodes."""
    defs: list[SymbolDef] = []
    for node in children:
        if node.type == "function_definition":
            _extract_python_func(node, source, defs, parent_class)
        elif node.type == "decorated_definition":
            _extract_python_decorated(node, source, defs, parent_class)
        elif node.type == "class_definition":
            _extract_python_class(node, source, defs)
    return defs


def _extract_python_func(
    node: Node,
    source: bytes,
    defs: list[SymbolDef],
    parent: str,
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
    node: Node,
    source: bytes,
    defs: list[SymbolDef],
    parent: str,
) -> None:
    """Extract definitions from decorated blocks."""
    for child in node.children:
        if child.type in ("function_definition", "class_definition"):
            defs.extend(_extract_python_children([child], source, parent))


def _extract_python_class(
    node: Node,
    source: bytes,
    defs: list[SymbolDef],
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
    node: Node,
    source: bytes,
    defs: list[SymbolDef],
    parent: str,
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
    node: Node,
    source: bytes,
    defs: list[SymbolDef],
    parent: str,
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
    node: Node,
    source: bytes,
    defs: list[SymbolDef],
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


# ── Per-function call extraction (caller-qualified) ─────────────────────

# Tree-sitter node types that represent a function/method definition
# across the grammars we support (Python/JS/TS/Go/Rust/Swift). We walk
# into each one and record the calls made inside its body, keyed by a
# qualified name that includes the enclosing class when applicable. The
# workflow graph's CALLS edges use this to surface WHICH caller made
# each call, not just that the call happened somewhere in the file.

_FUNCTION_NODE_TYPES = frozenset(
    {
        "function_definition",  # Python, Rust, Swift
        "function_declaration",  # JS, TS, Go, Swift
        "method_definition",  # JS, TS (class bodies)
        "method_declaration",  # TS interfaces, Go method receivers
        "function_signature",  # TS interfaces, Swift protocols
    }
)

# Class/impl-block containers whose children should carry a prefix.
_CLASS_NODE_TYPES = frozenset(
    {
        "class_definition",  # Python
        "class_declaration",  # JS, TS, Java, Kotlin
        "impl_item",  # Rust impl ClassName { ... }
    }
)

# Call-expression node types per grammar.
_CALL_NODE_TYPES = ("call", "call_expression")


def _callee_basename(call_node: Node, source: bytes) -> str:
    """Best-effort callee basename for resolution via symbol_to_file.

    Strategy: take the dotted/attribute chain's last segment and strip
    anything after the first ``(``, ``[``, or ``<`` (generics, subscripts,
    argument lists that slip into tree-sitter's surface text)."""
    fn_ref = call_node.child_by_field_name("function")
    if fn_ref is None:
        return ""
    text = _text(fn_ref, source).strip()
    base = text.rsplit(".", 1)[-1]
    for c in "([<":
        base = base.split(c, 1)[0]
    return base.strip()


def extract_calls_per_function(
    root: Node,
    source: bytes,
) -> dict[str, list[str]]:
    """Return ``{qualified_name: [callee_basename, ...]}``.

    Walks every function/method definition reachable from ``root``.
    Methods inside a class get ``ClassName.method`` as their qname
    (matching the shape ``extract_python_definitions`` already emits).
    Anonymous functions (lambdas, unnamed arrows) are skipped — no
    qname means we can't attach edges to them.
    """
    out: dict[str, list[str]] = {}
    _walk_for_calls(root, "", source, out)
    return out


def _walk_for_calls(
    node: Node,
    class_scope: str,
    source: bytes,
    out: dict[str, list[str]],
) -> None:
    """Walk ``node``'s descendants, tracking the enclosing class.

    Precondition: `out` is the accumulator `extract_calls_per_function`
    returns; this function only adds keys, it does not read existing ones.
    Postcondition: every named function/method reachable from `node` has
    its qualified name mapped to its deduped callee-basename list in `out`.

    Iterative for the same reason as `_walk_type`: one Python frame per AST
    level raised RecursionError on deeply nested sources, and no caller
    catches it. The explicit stack carries the enclosing class scope with
    each node, and descendants are pushed reversed so they pop before the
    remaining siblings — preserving the depth-first pre-order the recursive
    form had, and with it the insertion order of `out`.
    """
    stack: list[tuple[Node, str]] = [(c, class_scope) for c in reversed(node.children)]
    while stack:
        child, scope = stack.pop()
        ntype = child.type
        if ntype in _CLASS_NODE_TYPES:
            name_node = child.child_by_field_name("name")
            cls = _text(name_node, source) if name_node else scope
            # Equivalent-mutant note (#369): mutating "body" here, or the `or`
            # to `and`, is undetectable. The body node is itself a child, so
            # descending `child.children` reaches it via the catch-all and
            # finds the same definitions in the same order. The fallback stays
            # because grammars without a `body` field rely on it.
            body = child.child_by_field_name("body") or child
            inner = cls or scope
            stack.extend((c, inner) for c in reversed(body.children))
        elif ntype == "decorated_definition":
            # Mirrors `_extract_python_children`'s dispatch, where the same
            # branch is load-bearing: that function has no catch-all, so
            # without it a decorated definition is invisible. Here the `else`
            # below already reaches the wrapped node, which makes this arm
            # behaviourally identical today — and its mutants unkillable.
            #
            # It is kept, not deleted, because it is the seam for behaviour
            # that was never filled in: calls made *in the decorator*
            # (`@app.route("/api")`, `@retry(times=3)`) currently produce no
            # edge anywhere. Issue #372 carries the design decision and the
            # implementation; deleting the arm would foreclose the question
            # rather than answer it.
            stack.extend((c, scope) for c in reversed(child.children))
        elif ntype in _FUNCTION_NODE_TYPES:
            name_node = child.child_by_field_name("name")
            # Equivalent-mutant note (#369): the `else ""` arm is unreachable —
            # every node type in _FUNCTION_NODE_TYPES carries a name in all
            # grammars in use (verified by sweep). It stays as a guard against
            # a grammar that stops doing so, which would otherwise crash here.
            fn_name = _text(name_node, source) if name_node else ""
            body = child.child_by_field_name("body") or child
            if fn_name:
                qname = f"{scope}.{fn_name}" if scope else fn_name
                out[qname] = _collect_call_basenames(body, source)
            # Descend into the body for nested definitions (inner
            # functions, closures that define named functions).
            stack.extend((c, scope) for c in reversed(body.children))
        else:
            stack.extend((c, scope) for c in reversed(child.children))


def _collect_call_basenames(body: Node, source: bytes) -> list[str]:
    """Deduped, order-preserving callee basenames for every call under `body`."""
    calls: list[str] = []
    seen: set[str] = set()
    for call_type in _CALL_NODE_TYPES:
        for call in _walk_type(body, call_type):
            base = _callee_basename(call, source)
            if base and base not in seen and len(base) < _MAX_CALL_NAME_LEN:
                calls.append(base)
                seen.add(base)
    return calls
