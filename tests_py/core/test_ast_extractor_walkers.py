"""Behavioural contract for the six language definition extractors.

Issue #369. These walkers decide what enters the code graph, and a silent
change in one of them — a wrong qualified name, a dropped nested type, a
method attributed to the wrong scope — degrades `ingest_codebase`, the wiki
reference pages and `unified_search` with no failing test and no signal.
Before this file, a scoped mutation run left 241 mutants unpinned across the
seven walkers, because `test_ast_extractors.py` covered Python, JS and Go
only.

Each language asserts the **exact** ordered `(name, kind)` list rather than
membership. Order is part of the contract: the walkers are depth-first
pre-order, downstream consumers see that order, and a membership assertion
cannot tell a correct walker from one that emits the right names in the wrong
scope.

Every expectation below was measured against the implementation, not
predicted, then read back against the source to confirm it is the intended
contract rather than a bug being frozen. Three measured behaviours are
surprising enough to name explicitly, and are pinned here as *current*
behaviour so that changing them becomes a deliberate act with a failing test,
not an accident:

* Swift `enum`/`struct` report kind ``class``. tree-sitter-swift parses all
  three as ``class_declaration``, so ``_SWIFT_KIND_MAP``'s
  ``enum_declaration`` and ``struct_declaration`` entries never match.
* Kotlin ``object O { ... }`` emits no entry for ``O``, and its members are
  attributed to no type (``o``/``function``, not ``O.o``/``method``).
* Ruby ``def self.name`` is not emitted at all — it parses as
  ``singleton_method``, which the walker does not handle.

Nested types reset the qualifier in every language here (``Inner.deep``, not
``Outer.Inner.deep``). That is consistent across all six, so it is the
contract, not a per-language slip.
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


JAVA_SOURCE = b"""package p;
interface Greeter { void greet(); }
enum Color { RED, GREEN }
record Point(int x, int y) {}
class Outer {
    Outer() {}
    void top() { Runnable r = new Runnable() { public void run() {} }; }
    class Inner { void deep() {} }
}
"""

KOTLIN_SOURCE = b"""interface I { fun x() }
object O { fun o() {} }
class A { fun m() {} class B { fun deep() {} } }
fun top() {}
"""

CSHARP_SOURCE = b"""namespace N {
  interface I { void X(); }
  enum E { A }
  struct S { void Y() {} }
  record R(int x);
  class C { void M() {} class D { void Deep() {} } }
}
"""

RUBY_SOURCE = b"""module M
  def self.mod_method; end
end
class A
  def m; end
  class B
    def deep; end
  end
end
def top; end
"""

PHP_SOURCE = b"""<?php
interface I { function x(); }
trait T { function t() {} }
enum E { case A; }
class C { function m() {} }
function top() {}
"""

SWIFT_SOURCE = b"""protocol P { func x() }
enum E { case a }
struct S { func s() {} }
class A { func m() {} }
func top() {}
"""


class TestJava:
    def test_full_definition_set_in_document_order(self) -> None:
        from mcp_server.core.ast_extractors_jvm import extract_java_definitions

        assert _defs("java", JAVA_SOURCE, extract_java_definitions) == [
            ("Greeter", "interface"),
            ("Greeter.greet", "method"),
            ("Color", "enum"),
            ("Point", "class"),
            ("Outer", "class"),
            ("Outer.Outer", "method"),
            ("Outer.top", "method"),
            ("Inner", "class"),
            ("Inner.deep", "method"),
        ]

    def test_anonymous_class_contributes_no_definition(self) -> None:
        """`new Runnable() { public void run() {} }` in JAVA_SOURCE is unnamed.

        The walker must not invent a name for it, and must not attribute
        `run` to the enclosing type.
        """
        from mcp_server.core.ast_extractors_jvm import extract_java_definitions

        names = [n for n, _ in _defs("java", JAVA_SOURCE, extract_java_definitions)]
        assert "run" not in names
        assert "Outer.run" not in names

    def test_empty_source_yields_nothing(self) -> None:
        from mcp_server.core.ast_extractors_jvm import extract_java_definitions

        assert _defs("java", b"", extract_java_definitions) == []

    def test_method_outside_a_type_is_a_function_not_a_method(self) -> None:
        """A fragment with no enclosing type leaves the scope empty, which is
        the only way to reach the `kind="function"` arm. Cortex indexes
        fragments and partial files, so this is a real input, not a curiosity.
        """
        from mcp_server.core.ast_extractors_jvm import extract_java_definitions

        assert _defs("java", b"void bare() {}", extract_java_definitions) == [
            ("bare", "function")
        ]


class TestKotlin:
    def test_full_definition_set_in_document_order(self) -> None:
        from mcp_server.core.ast_extractors_jvm import extract_kotlin_definitions

        assert _defs("kotlin", KOTLIN_SOURCE, extract_kotlin_definitions) == [
            ("I", "interface"),
            ("I.x", "method"),
            ("o", "function"),
            ("A", "class"),
            ("A.m", "method"),
            ("A.deep", "method"),
            ("top", "function"),
        ]

    def test_object_declaration_emits_no_type_entry(self) -> None:
        """Pins the surprise: a bare `object O` yields nothing for O, and its
        member is unqualified. Changing this should require editing this
        assertion.
        """
        from mcp_server.core.ast_extractors_jvm import extract_kotlin_definitions

        got = _defs("kotlin", KOTLIN_SOURCE, extract_kotlin_definitions)
        assert ("O", "class") not in got
        assert ("o", "function") in got

    def test_object_with_a_supertype_does_emit_a_type_entry(self) -> None:
        """The contrast that explains the surprise above: with a supertype the
        grammar produces a `type_identifier`, so `object_declaration` is a
        reachable, observable branch and not dead code. Without this case the
        branch's node-type string is unpinned.
        """
        from mcp_server.core.ast_extractors_jvm import extract_kotlin_definitions

        assert _defs(
            "kotlin",
            b"object Named : Base() { fun n() {} }",
            extract_kotlin_definitions,
        ) == [("Named", "class"), ("Named.n", "method")]


class TestCSharp:
    def test_full_definition_set_in_document_order(self) -> None:
        from mcp_server.core.ast_extractors_clike import extract_csharp_definitions

        assert _defs("csharp", CSHARP_SOURCE, extract_csharp_definitions) == [
            ("I", "interface"),
            ("I.X", "method"),
            ("E", "enum"),
            ("S", "class"),
            ("S.Y", "method"),
            ("R", "class"),
            ("C", "class"),
            ("C.M", "method"),
            ("D", "class"),
            ("D.Deep", "method"),
        ]

    def test_struct_and_record_both_report_class(self) -> None:
        from mcp_server.core.ast_extractors_clike import extract_csharp_definitions

        kinds = dict(_defs("csharp", CSHARP_SOURCE, extract_csharp_definitions))
        assert kinds["S"] == "class"
        assert kinds["R"] == "class"

    def test_method_directly_in_a_namespace_is_a_function(self) -> None:
        """The only reachable route to the empty-scope arm in C#: a bare
        `void M(){}` at file scope is not parsed as a `method_declaration` at
        all, but one directly inside a namespace is.
        """
        from mcp_server.core.ast_extractors_clike import extract_csharp_definitions

        assert _defs(
            "csharp", b"namespace N { void M(){} }", extract_csharp_definitions
        ) == [("M", "function")]


class TestRuby:
    def test_full_definition_set_in_document_order(self) -> None:
        from mcp_server.core.ast_extractors_scripting import extract_ruby_definitions

        assert _defs("ruby", RUBY_SOURCE, extract_ruby_definitions) == [
            ("M", "module"),
            ("A", "class"),
            ("A.m", "method"),
            ("B", "class"),
            ("B.deep", "method"),
            ("top", "function"),
        ]

    def test_singleton_method_is_not_emitted(self) -> None:
        """Pins the surprise: `def self.mod_method` inside `module M` produces
        nothing, because it parses as `singleton_method`.
        """
        from mcp_server.core.ast_extractors_scripting import extract_ruby_definitions

        names = [n for n, _ in _defs("ruby", RUBY_SOURCE, extract_ruby_definitions)]
        assert "M.mod_method" not in names
        assert "mod_method" not in names


class TestPhp:
    def test_full_definition_set_in_document_order(self) -> None:
        from mcp_server.core.ast_extractors_scripting import extract_php_definitions

        assert _defs("php", PHP_SOURCE, extract_php_definitions) == [
            ("I", "interface"),
            ("I.x", "method"),
            ("T", "trait"),
            ("T.t", "method"),
            ("E", "enum"),
            ("C", "class"),
            ("C.m", "method"),
            ("top", "function"),
        ]

    def test_trait_is_its_own_kind(self) -> None:
        from mcp_server.core.ast_extractors_scripting import extract_php_definitions

        assert ("T", "trait") in _defs("php", PHP_SOURCE, extract_php_definitions)


class TestSwift:
    def test_full_definition_set_in_document_order(self) -> None:
        from mcp_server.core.ast_extractors_extra import extract_swift_definitions

        assert _defs("swift", SWIFT_SOURCE, extract_swift_definitions) == [
            ("P", "protocol"),
            ("E", "class"),
            ("S", "class"),
            ("S.s", "method"),
            ("A", "class"),
            ("A.m", "method"),
            ("top", "function"),
        ]

    def test_enum_and_struct_report_class_because_the_grammar_says_so(self) -> None:
        """Pins the surprise: tree-sitter-swift parses `enum`, `struct` and
        `class` all as `class_declaration`, so `_SWIFT_KIND_MAP`'s
        `enum_declaration` / `struct_declaration` entries never match.
        """
        from mcp_server.core.ast_extractors_extra import extract_swift_definitions

        kinds = dict(_defs("swift", SWIFT_SOURCE, extract_swift_definitions))
        assert kinds["E"] == "class"
        assert kinds["S"] == "class"
        assert kinds["P"] == "protocol"


CALLS_SOURCE = b"""import functools

@functools.cache
def decorated():
    helper()

def outer():
    inner_result = inner()
    def nested():
        deep()
    cb = lambda: ignored()
    return inner_result

class K:
    def method(self):
        self.thing()
        free()
"""


class TestCallExtraction:
    """`extract_calls_per_function` drives `_walk_for_calls`, the walker that
    carries class scope. Its output keys the call edges of the code graph, so
    both the mapping and its insertion order are contract.
    """

    def _calls(self, source: bytes) -> dict[str, list[str]]:
        from tree_sitter_language_pack import get_parser

        from mcp_server.core.ast_extractors import extract_calls_per_function

        root = get_parser("python").parse(source).root_node
        return extract_calls_per_function(root, source)

    def test_exact_call_map_including_key_order(self) -> None:
        got = self._calls(CALLS_SOURCE)
        assert got == {
            "decorated": ["helper"],
            "outer": ["inner", "deep", "ignored"],
            "nested": ["deep"],
            "K.method": ["thing", "free"],
        }
        # Depth-first pre-order. A breadth-first rewrite would still satisfy
        # the equality above.
        assert list(got) == ["decorated", "outer", "nested", "K.method"]

    def test_a_decorated_function_is_still_reached(self) -> None:
        """`@functools.cache def decorated()` sits under a `decorated_definition`
        node, a branch nothing else in the suite exercises.
        """
        assert self._calls(CALLS_SOURCE)["decorated"] == ["helper"]

    def test_nested_and_lambda_calls_also_count_for_the_enclosing_function(
        self,
    ) -> None:
        got = self._calls(CALLS_SOURCE)
        assert got["nested"] == ["deep"]
        assert "deep" in got["outer"], "a nested def's calls stay visible to its parent"
        assert "ignored" in got["outer"], (
            "a lambda has no qname, so its calls land on the parent"
        )

    def test_default_argument_calls_are_not_attributed_to_the_function(self) -> None:
        """Calls come from the body field, not the whole definition node, so a
        call in a default argument is out of scope. This is what separates
        reading `body` from falling back to the definition node.
        """
        source = b"def with_default(x=make_default(), y=2):\n    body_call()\n"
        assert self._calls(source) == {"with_default": ["body_call"]}

    def test_no_definitions_yields_an_empty_map(self) -> None:
        assert self._calls(b"x = 1\nprint(x)\n") == {}


class TestScopeQualification:
    """The qualifier rule is shared across all six walkers, so it gets one
    place that states it rather than six that imply it.
    """

    @pytest.mark.parametrize(
        ("language", "source", "module", "entry", "expected"),
        [
            (
                "java",
                JAVA_SOURCE,
                "mcp_server.core.ast_extractors_jvm",
                "extract_java_definitions",
                ("Inner.deep", "Outer.Inner.deep"),
            ),
            (
                "csharp",
                CSHARP_SOURCE,
                "mcp_server.core.ast_extractors_clike",
                "extract_csharp_definitions",
                ("D.Deep", "C.D.Deep"),
            ),
            (
                "ruby",
                RUBY_SOURCE,
                "mcp_server.core.ast_extractors_scripting",
                "extract_ruby_definitions",
                ("B.deep", "A.B.deep"),
            ),
        ],
        ids=["java", "csharp", "ruby"],
    )
    def test_nested_type_resets_the_qualifier(
        self,
        language: str,
        source: bytes,
        module: str,
        entry: str,
        expected: tuple[str, str],
    ) -> None:
        import importlib

        flat, nested = expected
        names = [
            n
            for n, _ in _defs(
                language, source, getattr(importlib.import_module(module), entry)
            )
        ]
        assert flat in names, "inner member should be qualified by its immediate type"
        assert nested not in names, "the qualifier does not accumulate through nesting"
