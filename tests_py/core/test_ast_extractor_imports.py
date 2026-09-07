"""Behavioural contract for every import extractor (issue #369).

Eleven languages, eleven extractors, and before this file most of them had no
test at all — 238 of the 639 unpinned mutants in the extractor modules lived
in import extraction. Imports are how the resolver links a symbol reference to
the file that defines it, so a dropped or malformed module string silently
degrades resolution across the whole graph rather than failing anywhere.

Each case asserts the exact ordered `(module, is_relative)` list. Several of
the expectations below are rough edges rather than polished behaviour. They
are pinned as *current* behaviour, with the rough edge named, so that changing
one is a deliberate act with a failing test rather than an accident. Where a
rough edge looks like a defect worth fixing, it says so; fixing it is not this
file's job.
"""

from __future__ import annotations

import pytest

from mcp_server.core.ast_parser import is_available

pytestmark = pytest.mark.skipif(
    not is_available(), reason="tree-sitter not installed; extractors are unreachable"
)


def _imports(language: str, source: bytes, extractor) -> list[tuple[str, bool]]:
    from tree_sitter_language_pack import get_parser

    root = get_parser(language).parse(source).root_node
    return [(i.module, i.is_relative) for i in extractor(root, source)]


class TestPythonImports:
    SOURCE = (
        b"import os\n"
        b"import os.path as p\n"
        b"from . import sibling\n"
        b"from ..pkg import thing, other as o\n"
        b"from collections.abc import Mapping\n"
    )

    def test_exact_import_list(self) -> None:
        from mcp_server.core.ast_extractors import extract_python_imports

        assert _imports("python", self.SOURCE, extract_python_imports) == [
            ("os", False),
            (".", True),
            ("..pkg", True),
            ("collections.abc", False),
        ]

    def test_aliased_plain_import_is_dropped(self) -> None:
        """Rough edge, pinned: `import os.path as p` yields nothing. The alias
        wraps the dotted_name in an `aliased_import`, so it is not a direct
        child and `_find_children` misses it. `from x import y as z` is not
        affected — only the plain `import a.b as c` form.
        """
        from mcp_server.core.ast_extractors import extract_python_imports

        assert (
            _imports("python", b"import os.path as p\n", extract_python_imports) == []
        )
        assert _imports("python", b"import os.path\n", extract_python_imports) == [
            ("os.path", False)
        ]

    def test_relative_depth_is_preserved_in_the_module_string(self) -> None:
        from mcp_server.core.ast_extractors import extract_python_imports

        assert _imports(
            "python", b"from ...deep import x\n", extract_python_imports
        ) == [("...deep", True)]


class TestJsImports:
    SOURCE = (
        b"import a from 'mod-a';\n"
        b"import {b, c} from './rel';\n"
        b"import * as ns from '../up';\n"
        b"require('cjs');\n"
    )

    def test_exact_import_list(self) -> None:
        from mcp_server.core.ast_extractors import extract_js_imports

        assert _imports("javascript", self.SOURCE, extract_js_imports) == [
            ("mod-a", False),
            ("./rel", True),
            ("../up", True),
        ]

    def test_commonjs_require_is_not_an_import(self) -> None:
        """Rough edge, pinned: only ES `import` statements are extracted, so a
        CommonJS `require()` contributes no edge. Real cost on Node codebases.
        """
        from mcp_server.core.ast_extractors import extract_js_imports

        assert (
            _imports("javascript", b"const x = require('cjs');\n", extract_js_imports)
            == []
        )

    def test_quote_style_does_not_change_the_module(self) -> None:
        from mcp_server.core.ast_extractors import extract_js_imports

        assert _imports("javascript", b'import a from "dq";\n', extract_js_imports) == [
            ("dq", False)
        ]


class TestJavaImports:
    def test_exact_import_list_including_static_and_wildcard(self) -> None:
        from mcp_server.core.ast_extractors_jvm import extract_java_imports

        source = (
            b"package p;\n"
            b"import java.util.List;\n"
            b"import static java.lang.Math.max;\n"
            b"import java.io.*;\n"
        )
        assert _imports("java", source, extract_java_imports) == [
            ("java.util.List", False),
            # `static` is not marked; the member becomes part of the path.
            ("java.lang.Math.max", False),
            # The wildcard survives into the module string verbatim.
            ("java.io.*", False),
        ]

    def test_package_declaration_is_not_an_import(self) -> None:
        from mcp_server.core.ast_extractors_jvm import extract_java_imports

        assert _imports("java", b"package p.q;\n", extract_java_imports) == []


class TestKotlinImports:
    def test_exact_import_list(self) -> None:
        from mcp_server.core.ast_extractors_jvm import extract_kotlin_imports

        source = b"package p\nimport kotlin.math.max\nimport foo.Bar as Baz\n"
        assert _imports("kotlin", source, extract_kotlin_imports) == [
            ("kotlin.math.max", False),
            # The alias is dropped, keeping the original path.
            ("foo.Bar", False),
        ]


class TestCImports:
    def test_angle_and_quoted_includes_are_both_captured_without_delimiters(
        self,
    ) -> None:
        from mcp_server.core.ast_extractors_clike import extract_c_imports

        source = b'#include <stdio.h>\n#include "local.h"\n'
        assert _imports("c", source, extract_c_imports) == [
            ("stdio.h", False),
            # Pinned rough edge: a quoted include is project-local by
            # convention, yet is_relative stays False.
            ("local.h", False),
        ]


class TestCSharpImports:
    def test_exact_using_list(self) -> None:
        from mcp_server.core.ast_extractors_clike import extract_csharp_imports

        source = (
            b"using System;\n"
            b"using System.Collections.Generic;\n"
            b"using Alias = Some.Thing;\n"
        )
        assert _imports("csharp", source, extract_csharp_imports) == [
            ("System", False),
            ("System.Collections.Generic", False),
            # Rough edge, pinned: an alias directive is captured verbatim,
            # spaces and all, rather than resolved to `Some.Thing`.
            ("Alias = Some.Thing", False),
        ]


class TestRubyImports:
    def test_require_forms(self) -> None:
        from mcp_server.core.ast_extractors_scripting import extract_ruby_imports

        source = b"require 'json'\nrequire_relative 'helper'\nload 'x.rb'\n"
        assert _imports("ruby", source, extract_ruby_imports) == [
            ("json", False),
            # Rough edge, pinned: `require_relative` is by definition relative
            # and still reports is_relative False.
            ("helper", False),
            ("x.rb", False),
        ]


class TestPhpImports:
    def test_use_and_group_use(self) -> None:
        from mcp_server.core.ast_extractors_scripting import extract_php_imports

        source = b"<?php\nuse App\\Models\\User;\nuse App\\{A, B};\nrequire 'f.php';\n"
        assert _imports("php", source, extract_php_imports) == [
            ("App\\Models\\User", False),
            # Rough edge, pinned: a group use loses its `App\` prefix, so `A`
            # and `B` are unresolvable as written.
            ("A", False),
            ("B", False),
        ]


class TestGoImports:
    def test_single_grouped_and_aliased(self) -> None:
        from mcp_server.core.ast_extractors_extra import extract_go_imports

        source = b'package main\nimport "fmt"\nimport (\n  "os"\n  m "math"\n)\n'
        assert _imports("go", source, extract_go_imports) == [
            ("fmt", False),
            ("os", False),
            # The alias is dropped and the real path kept — the opposite of
            # C#'s behaviour above, and the more useful one.
            ("math", False),
        ]


class TestSwiftImports:
    def test_module_imports(self) -> None:
        from mcp_server.core.ast_extractors_extra import extract_swift_imports

        assert _imports(
            "swift", b"import Foundation\nimport UIKit\n", extract_swift_imports
        ) == [("Foundation", False), ("UIKit", False)]


class TestRustImports:
    def test_use_declarations_are_captured_verbatim(self) -> None:
        from mcp_server.core.ast_extractors_extra import extract_rust_imports

        source = (
            b"use std::io;\n"
            b"use std::collections::{HashMap, HashSet};\n"
            b"use crate::thing as t;\n"
        )
        assert _imports("rust", source, extract_rust_imports) == [
            ("std::io", False),
            # Rough edges, pinned: a brace group is not expanded into its
            # members, and an `as` clause is not stripped. Neither string
            # resolves to a path.
            ("std::collections::{HashMap, HashSet}", False),
            ("crate::thing as t", False),
        ]

    def test_crate_relative_paths_are_not_marked_relative(self) -> None:
        from mcp_server.core.ast_extractors_extra import extract_rust_imports

        assert _imports("rust", b"use crate::a::b;\n", extract_rust_imports) == [
            ("crate::a::b", False)
        ]


class TestEmptyAndUnparseable:
    """Every extractor must return an empty list rather than raising on input
    with nothing to find. Cortex indexes whatever is in the tree.
    """

    @pytest.mark.parametrize(
        ("language", "module", "entry"),
        [
            ("python", "mcp_server.core.ast_extractors", "extract_python_imports"),
            ("javascript", "mcp_server.core.ast_extractors", "extract_js_imports"),
            ("java", "mcp_server.core.ast_extractors_jvm", "extract_java_imports"),
            ("kotlin", "mcp_server.core.ast_extractors_jvm", "extract_kotlin_imports"),
            ("c", "mcp_server.core.ast_extractors_clike", "extract_c_imports"),
            (
                "csharp",
                "mcp_server.core.ast_extractors_clike",
                "extract_csharp_imports",
            ),
            (
                "ruby",
                "mcp_server.core.ast_extractors_scripting",
                "extract_ruby_imports",
            ),
            ("php", "mcp_server.core.ast_extractors_scripting", "extract_php_imports"),
            ("go", "mcp_server.core.ast_extractors_extra", "extract_go_imports"),
            ("swift", "mcp_server.core.ast_extractors_extra", "extract_swift_imports"),
            ("rust", "mcp_server.core.ast_extractors_extra", "extract_rust_imports"),
        ],
    )
    def test_empty_source_yields_no_imports(
        self, language: str, module: str, entry: str
    ) -> None:
        import importlib

        assert (
            _imports(language, b"", getattr(importlib.import_module(module), entry))
            == []
        )
