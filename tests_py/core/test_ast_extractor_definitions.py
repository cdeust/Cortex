"""Behavioural contract for the remaining definition extractors (issue #369).

Companion to `test_ast_extractor_walkers.py`, which covered the six
scope-tracking walkers. This file covers what was left: C, C++, Go, Rust,
Python and JS/TS definition extraction, plus the callee-basename resolution
that turns a call node into a graph edge.

Same discipline as the walker file: assert the **exact ordered** result, and
measure the expectation against the implementation before asserting it rather
than predicting it. Order matters — several of these extractors run separate
passes per node type, so the output is not source order and a consumer reading
it positionally depends on the pass order.

Rough edges are pinned as current behaviour with the cause named, not quietly
frozen. Where one looks like a defect, it says so.
"""

from __future__ import annotations

import pytest

from mcp_server.core.ast_parser import is_available

pytestmark = pytest.mark.skipif(
    not is_available(), reason="tree-sitter not installed; extractors are unreachable"
)


def _defs(language: str, source: bytes, extractor) -> list[tuple[str, str]]:
    from tree_sitter_language_pack import get_parser

    root = get_parser(language).parse(source).root_node
    return [(d.name, d.kind) for d in extractor(root, source)]


def _sigs(language: str, source: bytes, extractor) -> dict[str, str]:
    from tree_sitter_language_pack import get_parser

    root = get_parser(language).parse(source).root_node
    return {d.name: getattr(d, "signature", "") for d in extractor(root, source)}


class TestCDefinitions:
    SOURCE = (
        b"#include <s.h>\n"
        b"struct P { int x; };\n"
        b"typedef struct P Point;\n"
        b"int add(int a, int b) { return a+b; }\n"
        b"static void helper(void) {}\n"
    )

    def test_exact_definition_list_functions_then_types(self) -> None:
        """Not source order: `extract_c_definitions` runs one `_walk_type` pass
        per node kind, so every function precedes every struct and typedef.
        """
        from mcp_server.core.ast_extractors_clike import extract_c_definitions

        assert _defs("c", self.SOURCE, extract_c_definitions) == [
            ("add", "function"),
            ("helper", "function"),
            ("P", "class"),
            ("P", "class"),
            ("Point", "type"),
        ]

    def test_a_struct_named_in_a_typedef_is_emitted_twice(self) -> None:
        """Rough edge, pinned. `struct P {...};` and `typedef struct P Point;`
        each contain a `struct_specifier`, and both passes emit it, so `P`
        appears twice with no deduplication. A consumer counting definitions
        over-counts, and a symbol table keyed by name silently collapses them.
        """
        from mcp_server.core.ast_extractors_clike import extract_c_definitions

        names = [n for n, _ in _defs("c", self.SOURCE, extract_c_definitions)]
        assert names.count("P") == 2

    def test_struct_alone_is_emitted_once(self) -> None:
        from mcp_server.core.ast_extractors_clike import extract_c_definitions

        assert _defs("c", b"struct P { int x; };\n", extract_c_definitions) == [
            ("P", "class")
        ]


class TestCppDefinitions:
    SOURCE = (
        b"namespace ns { class C { public: void m(); }; struct S {}; }\n"
        b"void ns::C::m() {}\n"
        b"int free_fn(int a) { return a; }\n"
        b"using namespace std;\n"
    )

    def test_exact_definition_list(self) -> None:
        from mcp_server.core.ast_extractors_clike import extract_cpp_definitions

        assert _defs("cpp", self.SOURCE, extract_cpp_definitions) == [
            ("C", "class"),
            ("ns", "namespace"),
            ("ns::C::m", "method"),
            ("free_fn", "function"),
        ]

    def test_a_struct_inside_a_namespace_is_not_emitted(self) -> None:
        """Rough edge, pinned: C++ extraction looks for `class_specifier`, so
        `struct S {}` produces nothing — unlike the C extractor, which does
        pick struct up. Same keyword, two different answers per language.
        """
        from mcp_server.core.ast_extractors_clike import extract_cpp_definitions

        assert "S" not in [
            n for n, _ in _defs("cpp", self.SOURCE, extract_cpp_definitions)
        ]

    def test_out_of_line_member_definition_keeps_its_qualified_name(self) -> None:
        from mcp_server.core.ast_extractors_clike import extract_cpp_definitions

        assert ("ns::C::m", "method") in _defs(
            "cpp", self.SOURCE, extract_cpp_definitions
        )


class TestGoDefinitions:
    SOURCE = (
        b"package main\n"
        b"type Server struct { port int }\n"
        b"type Handler interface { Serve() }\n"
        b"func (s *Server) Start() error { return nil }\n"
        b"func (s Server) Stop() {}\n"
        b"func New(p int) *Server { return nil }\n"
    )

    def test_exact_definition_list(self) -> None:
        from mcp_server.core.ast_extractors_extra import extract_go_definitions

        assert _defs("go", self.SOURCE, extract_go_definitions) == [
            ("Server", "struct"),
            ("Handler", "interface"),
            ("Server.Start", "method"),
            ("Server.Stop", "method"),
            ("New", "function"),
        ]

    def test_pointer_and_value_receivers_qualify_identically(self) -> None:
        """`*Server` and `Server` both yield `Server.` — the star is stripped,
        so the two receiver forms do not fragment the symbol table.
        """
        from mcp_server.core.ast_extractors_extra import extract_go_definitions

        names = [n for n, _ in _defs("go", self.SOURCE, extract_go_definitions)]
        assert "Server.Start" in names and "Server.Stop" in names

    def test_function_signature_is_captured(self) -> None:
        from mcp_server.core.ast_extractors_extra import extract_go_definitions

        assert _sigs("go", self.SOURCE, extract_go_definitions)["New"] == "(p int)"


class TestRustDefinitions:
    SOURCE = (
        b"pub struct S { x: i32 }\n"
        b"enum E { A, B }\n"
        b"trait T { fn t(&self); }\n"
        b"impl S { pub fn new() -> Self { S{x:0} } fn helper(&self) {} }\n"
        b"impl T for S { fn t(&self) {} }\n"
        b"fn free() {}\n"
        b"mod m { fn inner() {} }\n"
    )

    def test_exact_definition_list(self) -> None:
        from mcp_server.core.ast_extractors_extra import extract_rust_definitions

        assert _defs("rust", self.SOURCE, extract_rust_definitions) == [
            ("S", "class"),
            ("E", "enum"),
            ("T", "trait"),
            ("S.new", "method"),
            ("S.helper", "method"),
            ("S.t", "method"),
            ("free", "function"),
        ]

    def test_inherent_and_trait_impl_methods_both_qualify_by_the_type(self) -> None:
        """`impl S` and `impl T for S` both attribute to `S`, so a trait
        implementation is not lost and not filed under the trait.
        """
        from mcp_server.core.ast_extractors_extra import extract_rust_definitions

        names = [n for n, _ in _defs("rust", self.SOURCE, extract_rust_definitions)]
        assert "S.new" in names and "S.t" in names
        assert "T.t" not in names

    def test_functions_inside_a_module_block_are_dropped(self) -> None:
        """Rough edge, pinned: `mod m { fn inner() {} }` yields nothing for
        `inner`. Rust codebases that group code in inline modules lose those
        definitions entirely.
        """
        from mcp_server.core.ast_extractors_extra import extract_rust_definitions

        names = [n for n, _ in _defs("rust", self.SOURCE, extract_rust_definitions)]
        assert "inner" not in names
        assert "m.inner" not in names


class TestPythonDefinitions:
    SOURCE = (
        b"@deco\n"
        b"class C(Base):\n"
        b"    @property\n"
        b"    def p(self): pass\n"
        b"    async def a(self): pass\n"
        b"async def top(): pass\n"
        b"@wrap\n"
        b"def decorated(x=1): pass\n"
    )

    def test_exact_definition_list(self) -> None:
        from mcp_server.core.ast_extractors import extract_python_definitions

        assert _defs("python", self.SOURCE, extract_python_definitions) == [
            ("C", "class"),
            ("C.p", "method"),
            ("C.a", "method"),
            ("top", "function"),
            ("decorated", "function"),
        ]

    def test_decorated_class_and_decorated_function_are_both_unwrapped(self) -> None:
        """`_extract_python_children` has no catch-all, so a decorated
        definition is only reached by its dedicated arm. Both `@deco class C`
        and `@wrap def decorated` depend on it.
        """
        from mcp_server.core.ast_extractors import extract_python_definitions

        names = [n for n, _ in _defs("python", self.SOURCE, extract_python_definitions)]
        assert "C" in names and "decorated" in names

    def test_async_def_is_a_definition_like_any_other(self) -> None:
        from mcp_server.core.ast_extractors import extract_python_definitions

        assert ("top", "function") in _defs(
            "python", self.SOURCE, extract_python_definitions
        )

    def test_signatures_carry_parameters_and_superclasses(self) -> None:
        from mcp_server.core.ast_extractors import extract_python_definitions

        sigs = _sigs("python", self.SOURCE, extract_python_definitions)
        assert sigs["C"] == "(Base)"
        assert sigs["decorated"] == "(x=1)"
        assert sigs["C.p"] == "(self)"


class TestJsDefinitions:
    SOURCE = (
        b"export class R { get(p){} static s(){} }\n"
        b"export interface I { k: string }\n"
        b"export type T = { v: boolean };\n"
        b"export function f(a){}\n"
        b"function g(){}\n"
    )

    def test_exact_definition_list(self) -> None:
        from mcp_server.core.ast_extractors import extract_js_definitions

        assert _defs("typescript", self.SOURCE, extract_js_definitions) == [
            ("R", "class"),
            ("R.get", "method"),
            ("R.s", "method"),
            ("I", "interface"),
            ("T", "type"),
            ("f", "function"),
            ("g", "function"),
        ]

    def test_export_wrapper_is_transparent(self) -> None:
        """`_extract_js_node` descends `export_statement` explicitly. Without
        that arm every exported definition — the majority of a TS codebase —
        would be invisible.
        """
        from mcp_server.core.ast_extractors import extract_js_definitions

        assert _defs(
            "typescript", b"export function only(){}\n", extract_js_definitions
        ) == [("only", "function")]

    def test_static_and_instance_methods_qualify_identically(self) -> None:
        from mcp_server.core.ast_extractors import extract_js_definitions

        names = [n for n, _ in _defs("typescript", self.SOURCE, extract_js_definitions)]
        assert "R.get" in names and "R.s" in names


class TestCalleeBasename:
    """`_callee_basename` turns a call node into the name the resolver looks
    up. Every call edge in the graph goes through it.
    """

    def _calls(self, language: str, source: bytes) -> dict[str, list[str]]:
        from tree_sitter_language_pack import get_parser

        from mcp_server.core.ast_extractors import extract_calls_per_function

        root = get_parser(language).parse(source).root_node
        return extract_calls_per_function(root, source)

    SOURCE = (
        b"def f():\n"
        b"    plain()\n"
        b"    obj.attr_call()\n"
        b"    a.b.c.deep()\n"
        b'    d["k"].sub()\n'
        b"    (lambda: 1)()\n"
        b"    Klass()\n"
        b"    self.method()\n"
        b"    plain()\n"
    )

    def test_basename_resolution_across_callee_shapes(self) -> None:
        """Attribute, chained-attribute and subscript callees all reduce to the
        final name. An immediately-invoked lambda has no name and contributes
        nothing. The repeated `plain()` appears once — the list is deduped and
        order-preserving.
        """
        assert self._calls("python", self.SOURCE) == {
            "f": ["plain", "attr_call", "deep", "sub", "Klass", "method"]
        }

    def test_javascript_new_expression_is_not_a_call(self) -> None:
        """Rough edge, pinned: `new Klass()` is a `new_expression`, which is
        not in `_CALL_NODE_TYPES`, so construction produces no edge.
        """
        source = b"function f() { plain(); obj.attr(); a.b.c.deep(); new Klass(); }\n"
        assert self._calls("javascript", source) == {"f": ["plain", "attr", "deep"]}

    def test_absurdly_long_callee_names_are_dropped(self) -> None:
        """`_MAX_CALL_NAME_LEN` is a sanity cap: a callee name at or beyond it
        is noise, not a symbol. Pins the constant so a silent bump is visible.
        """
        source = b"def f():\n    " + b"x" * 150 + b"()\n"
        assert self._calls("python", source) == {"f": []}

    def test_a_name_just_under_the_cap_is_kept(self) -> None:
        name = b"y" * 99
        source = b"def f():\n    " + name + b"()\n"
        assert self._calls("python", source) == {"f": [name.decode()]}


class TestCppDeclaratorName:
    """`_declarator_name` resolves the name out of a C++ declarator. Its two
    node-type tuples cover the plain and the qualified/special forms, and a
    simple `void f()` fixture only ever reaches the first entry of the first
    tuple.
    """

    def test_an_out_of_line_destructor_keeps_its_qualified_name(self) -> None:
        from mcp_server.core.ast_extractors_clike import extract_cpp_definitions

        source = b"class C { public: ~C(); };\nC::~C() {}\n"
        assert _defs("cpp", source, extract_cpp_definitions) == [
            ("C", "class"),
            ("C::~C", "method"),
        ]

    def test_a_plain_free_function_uses_the_identifier_form(self) -> None:
        from mcp_server.core.ast_extractors_clike import extract_cpp_definitions

        assert _defs(
            "cpp", b"int f(int a) { return a; }\n", extract_cpp_definitions
        ) == [("f", "function")]
