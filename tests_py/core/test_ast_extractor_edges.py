"""Boundary and detail contract for the extractors (issue #369, round two).

`test_ast_extractor_imports.py` and `test_ast_extractor_definitions.py` pinned
the shape of the output. Mutation testing then showed what shape alone misses:
fields nobody asserted (`ImportInfo.names`), the exact truncation boundary of a
signature, the exact length cap on a callee name, and the character sets used
to clean up module strings. Each of those is a constant or a field that a
change could move silently while every existing assertion still passed.

The fixtures here are deliberately awkward — module paths ending in ``X``, a
callee containing ``X``, a name of exactly the cap length, bytes that are not
valid UTF-8. That awkwardness is the point: an ordinary fixture cannot
distinguish ``rstrip(";")`` from ``rstrip("X;X")`` or ``len(x) < 100`` from
``<= 100``, so an ordinary fixture leaves those free to drift.
"""

from __future__ import annotations

import pytest

from mcp_server.core.ast_parser import is_available

pytestmark = pytest.mark.skipif(
    not is_available(), reason="tree-sitter not installed; extractors are unreachable"
)


def _root(language: str, source: bytes):
    from tree_sitter_language_pack import get_parser

    return get_parser(language).parse(source).root_node


def _full_imports(
    language: str, source: bytes, extractor
) -> list[tuple[str, list[str], bool]]:
    return [
        (i.module, list(i.names), i.is_relative)
        for i in extractor(_root(language, source), source)
    ]


class TestImportNames:
    """`ImportInfo.names` carries the imported symbols. Nothing asserted it
    before, so the whole name-collection path was free to change silently —
    which matters because the resolver uses those names to bind a reference to
    a definition, not just the module.
    """

    def test_python_names_are_collected_and_exclude_the_module(self) -> None:
        from mcp_server.core.ast_extractors import extract_python_imports

        source = b"from ..pkg import thing, other as o\nfrom a.b import c\nimport os\n"
        assert _full_imports("python", source, extract_python_imports) == [
            # The module node itself must not leak into names.
            ("..pkg", ["thing", "other as o"], True),
            ("a.b", ["c"], False),
            # A plain `import os` has a module and no names.
            ("os", [], False),
        ]

    def test_an_alias_is_kept_verbatim_in_names(self) -> None:
        """Rough edge, pinned: `other as o` is stored as one string rather than
        resolved to either side, so a consumer matching on `other` misses it.
        """
        from mcp_server.core.ast_extractors import extract_python_imports

        source = b"from m import other as o\n"
        assert _full_imports("python", source, extract_python_imports) == [
            ("m", ["other as o"], False)
        ]


class TestGoTypeKind:
    def test_a_non_struct_non_interface_type_reports_kind_type(self) -> None:
        """`type ID int` is the only route to the `type` kind; struct and
        interface take the other two arms.
        """
        from mcp_server.core.ast_extractors_extra import extract_go_definitions

        source = b"package m\ntype ID int\n"
        got = [
            (d.name, d.kind)
            for d in extract_go_definitions(_root("go", source), source)
        ]
        assert got == [("ID", "type")]

    def test_a_type_alias_is_not_emitted(self) -> None:
        """Rough edge, pinned: `type Alias = string` produces nothing."""
        from mcp_server.core.ast_extractors_extra import extract_go_definitions

        source = b"package m\ntype Alias = string\n"
        assert extract_go_definitions(_root("go", source), source) == []


class TestSignatureTruncation:
    """Signatures are capped at 120 characters. The cap is a constant nobody
    pinned, so it could move a character in either direction unnoticed.
    """

    LONG_PARAMS = b"def f(" + b", ".join(b"p%d=1" % i for i in range(40)) + b"): pass\n"

    def test_a_long_python_signature_is_cut_at_exactly_120(self) -> None:
        from mcp_server.core.ast_extractors import extract_python_definitions

        defs = extract_python_definitions(
            _root("python", self.LONG_PARAMS), self.LONG_PARAMS
        )
        assert [d.name for d in defs] == ["f"]
        assert len(defs[0].signature) == 120

    def test_a_long_python_superclass_list_is_cut_at_exactly_120(self) -> None:
        from mcp_server.core.ast_extractors import extract_python_definitions

        bases = b", ".join(b"Base%d" % i for i in range(40))
        source = b"class C(" + bases + b"): pass\n"
        defs = extract_python_definitions(_root("python", source), source)
        assert len(defs[0].signature) == 120

    def test_a_class_with_no_base_list_has_an_empty_signature(self) -> None:
        """`class C: pass` has no `superclasses` node, so the signature falls
        back to the empty string. That fallback is otherwise never exercised.
        """
        from mcp_server.core.ast_extractors import extract_python_definitions

        source = b"class C: pass\n"
        defs = extract_python_definitions(_root("python", source), source)
        assert [(d.name, d.signature) for d in defs] == [("C", "")]

    def test_a_long_go_signature_is_cut_at_exactly_120(self) -> None:
        from mcp_server.core.ast_extractors_extra import extract_go_definitions

        params = b", ".join(b"p%d int" % i for i in range(30))
        source = b"package m\nfunc F(" + params + b") {}\n"
        defs = extract_go_definitions(_root("go", source), source)
        assert len(defs[0].signature) == 120

    def test_a_short_signature_is_not_padded_or_cut(self) -> None:
        from mcp_server.core.ast_extractors import extract_python_definitions

        source = b"def f(a, b): pass\n"
        defs = extract_python_definitions(_root("python", source), source)
        assert defs[0].signature == "(a, b)"

    def test_javascript_functions_carry_their_parameter_list(self) -> None:
        from mcp_server.core.ast_extractors import extract_js_definitions

        source = b"function f(a, b) {}\n"
        defs = extract_js_definitions(_root("typescript", source), source)
        assert [(d.name, d.signature) for d in defs] == [("f", "(a, b)")]

    def test_a_long_javascript_signature_is_cut_at_exactly_120(self) -> None:
        from mcp_server.core.ast_extractors import extract_js_definitions

        params = b", ".join(b"p%d" % i for i in range(60))
        source = b"function f(" + params + b") {}\n"
        defs = extract_js_definitions(_root("typescript", source), source)
        assert len(defs[0].signature) == 120

    def test_go_functions_carry_their_parameter_list(self) -> None:
        from mcp_server.core.ast_extractors_extra import extract_go_definitions

        source = b"package m\nfunc New(p int) *S { return nil }\n"
        defs = extract_go_definitions(_root("go", source), source)
        assert [(d.name, d.signature) for d in defs] == [("New", "(p int)")]


class TestCalleeBasenameEdges:
    def _calls(self, language: str, source: bytes) -> dict[str, list[str]]:
        from mcp_server.core.ast_extractors import extract_calls_per_function

        return extract_calls_per_function(_root(language, source), source)

    def test_a_callee_containing_an_uppercase_x_is_not_truncated(self) -> None:
        """The basename is split on each of `(`, `[`, `<`. Widening that
        character set — even by an unrelated letter — silently mangles any name
        containing it, and `X` is the character mutation testing inserts.
        """
        assert self._calls("python", b"def f():\n    maXker()\n") == {"f": ["maXker"]}

    def test_a_generic_callee_keeps_only_the_name_before_the_first_bracket(
        self,
    ) -> None:
        """`foo<Bar<Baz>>()` must reduce to `foo`, not `foo<Bar`. Splitting
        from the right instead of the left gets this wrong.
        """
        source = b"function f() { foo<Bar<Baz>>(); }\n"
        assert self._calls("typescript", source) == {"f": ["foo"]}

    def test_the_length_cap_excludes_a_name_of_exactly_the_cap(self) -> None:
        """`len(base) < _MAX_CALL_NAME_LEN`, strictly. A name of exactly 100
        characters is dropped; 99 is kept. Pins the comparison, not just the
        constant.
        """
        source = b"def f():\n    " + b"z" * 100 + b"()\n"
        assert self._calls("python", source) == {"f": []}

    def test_a_name_one_below_the_cap_is_kept(self) -> None:
        name = b"z" * 99
        source = b"def f():\n    " + name + b"()\n"
        assert self._calls("python", source) == {"f": [name.decode()]}

    def test_a_nested_subscript_callee_keeps_only_the_root_name(self) -> None:
        """`a[b[c]]()` is the case with two of the same bracket in the callee
        text. Splitting on the first `[` gives `a`; splitting on the last gives
        `a[b`, a symbol that does not exist. One `[` cannot tell the two apart.
        """
        assert self._calls("python", b"def f():\n    a[b[c]]()\n") == {"f": ["a"]}

    def test_a_parenthesised_callee_expression_yields_no_edge(self) -> None:
        """`(a or b)()` has no resolvable name. Splitting the callee text on
        the *first* bracket leaves an empty string, which is correctly
        discarded; splitting on the last would leave `(a or b` and invent a
        symbol that does not exist.
        """
        assert self._calls("python", b"def f():\n    (a or b)()\n") == {"f": []}


class TestModuleStringCleanup:
    """Each import extractor trims keywords, quotes and terminators from the
    raw source text. The trimmed character sets are constants, and an ordinary
    module path cannot tell a correct set from a wider one — every fixture here
    ends in a character the wider set would eat.
    """

    def test_java_keeps_a_path_whose_segments_contain_the_keyword(self) -> None:
        from mcp_server.core.ast_extractors_jvm import extract_java_imports

        source = b"import com.importX.ThingX;\n"
        assert _full_imports("java", source, extract_java_imports) == [
            ("com.importX.ThingX", [], False)
        ]

    def test_java_static_import_strips_the_keyword_only_once(self) -> None:
        """`import static a.staticX.b;` contains the word twice. Only the
        leading keyword is a keyword; the one inside a path segment is part of
        the name and must survive.
        """
        from mcp_server.core.ast_extractors_jvm import extract_java_imports

        source = b"import static a.staticX.b;\n"
        assert _full_imports("java", source, extract_java_imports) == [
            ("a.staticX.b", [], False)
        ]

    def test_csharp_keeps_a_path_whose_segment_contains_the_keyword(self) -> None:
        from mcp_server.core.ast_extractors_clike import extract_csharp_imports

        source = b"using Some.usingX;\n"
        assert _full_imports("c_sharp", source, extract_csharp_imports) == [
            ("Some.usingX", [], False)
        ]

    def test_php_strips_only_the_terminator(self) -> None:
        from mcp_server.core.ast_extractors_scripting import extract_php_imports

        source = b"<?php\nuse App\\ThingX;\n"
        assert _full_imports("php", source, extract_php_imports) == [
            ("App\\ThingX", [], False)
        ]

    def test_rust_strips_only_the_terminator(self) -> None:
        from mcp_server.core.ast_extractors_extra import extract_rust_imports

        assert _full_imports("rust", b"use std::ioX;\n", extract_rust_imports) == [
            ("std::ioX", [], False)
        ]

    def test_go_strips_only_the_quotes(self) -> None:
        from mcp_server.core.ast_extractors_extra import extract_go_imports

        source = b'package m\nimport "fmtX"\n'
        assert _full_imports("go", source, extract_go_imports) == [("fmtX", [], False)]

    def test_c_strips_only_quotes_and_angle_brackets(self) -> None:
        from mcp_server.core.ast_extractors_clike import extract_c_imports

        source = b'#include "XlocalX"\n'
        assert _full_imports("c", source, extract_c_imports) == [("XlocalX", [], False)]

    def test_javascript_strips_only_the_quotes(self) -> None:
        from mcp_server.core.ast_extractors import extract_js_imports

        source = b"import a from 'XmodX';\n"
        assert _full_imports("javascript", source, extract_js_imports) == [
            ("XmodX", [], False)
        ]


class TestRubyRequireScanning:
    def test_non_require_calls_are_skipped_without_ending_the_scan(self) -> None:
        """A `puts` between two `require`s must be skipped, not treated as a
        stopping point. Turning the skip into a break would silently drop every
        import after the first unrelated call — extremely common in Ruby.
        """
        from mcp_server.core.ast_extractors_scripting import extract_ruby_imports

        source = b"puts 'hi'\nrequire 'json'\nputs 'bye'\nrequire 'yaml'\n"
        assert _full_imports("ruby", source, extract_ruby_imports) == [
            ("json", [], False),
            ("yaml", [], False),
        ]

    def test_a_call_with_no_method_name_does_not_abort_the_scan(self) -> None:
        from mcp_server.core.ast_extractors_scripting import extract_ruby_imports

        source = b"require 'json'\n"
        assert _full_imports("ruby", source, extract_ruby_imports) == [
            ("json", [], False)
        ]

    def test_only_quotes_and_parentheses_are_trimmed_from_the_path(self) -> None:
        """Both call forms are trimmed of their own punctuation and nothing
        else. A path whose first and last characters are ordinary letters must
        keep them, which is what distinguishes the real trim set from a wider
        one.
        """
        from mcp_server.core.ast_extractors_scripting import extract_ruby_imports

        source = b"require 'XjsonX'\nrequire('XyamlX')\n"
        assert _full_imports("ruby", source, extract_ruby_imports) == [
            ("XjsonX", [], False),
            ("XyamlX", [], False),
        ]


class TestNonUtf8Source:
    def test_invalid_bytes_inside_a_node_decode_to_the_replacement_character(
        self,
    ) -> None:
        """`_text` decodes with `errors="replace"`. Cortex indexes whatever is
        on disk, including files that are not valid UTF-8, and an unusable
        error handler would raise `LookupError` out of the indexer the moment
        one appeared. Valid UTF-8 never consults the handler, so only a
        genuinely invalid byte exercises it.
        """
        from mcp_server.core.ast_extractors import extract_js_imports

        source = b"import a from 'p\xffq';\n"
        assert _full_imports("javascript", source, extract_js_imports) == [
            ("p�q", [], False)
        ]

    def test_a_c_include_with_invalid_bytes_also_survives(self) -> None:
        from mcp_server.core.ast_extractors_clike import extract_c_imports

        source = b'#include "h\xffk.h"\n'
        assert _full_imports("c", source, extract_c_imports) == [("h�k.h", [], False)]
