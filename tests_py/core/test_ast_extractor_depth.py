"""Depth contract for the tree-sitter extractors that walk a whole AST.

The extractors walk an AST whose depth is set by untrusted input: Cortex
indexes third-party repositories, and minified or generated sources nest far
deeper than hand-written code. Every full-tree walker used to spend one Python
frame per AST level, so a deep file raised `RecursionError` — and nothing in
`mcp_server/` catches it (`grep -rn "RecursionError" mcp_server/` is empty), so
it propagated out of the indexer and failed the run for the whole repository.
Reproduced before the fix at an AST depth of ~1003 against the default
recursion limit of 1000.

Two properties are asserted per case, because either alone is insufficient:

1. The fixture's AST is genuinely deeper than the interpreter's limit. Without
   this a parser change that flattens the tree would leave the test green while
   testing nothing.
2. The nesting sits where the walker actually descends. The language walkers
   `return` at a method node without entering its body, so deep nesting inside
   a method body never reaches the recursive path — every fixture below was
   verified to raise `RecursionError` against the pre-fix implementation, and a
   method-body fixture was rejected for exactly this reason.

`extract_python_definitions` and `extract_js_definitions` are deliberately
absent: neither descends the full tree (`_extract_js_node` recurses only
through `export_statement`), so a depth case for them would be vacuous. The
JS/Python exposure runs through `_walk_type`, covered in
`test_ast_extractors.py::TestWalkType`.
"""

from __future__ import annotations

import importlib
import sys

import pytest

from mcp_server.core.ast_parser import is_available

pytestmark = pytest.mark.skipif(
    not is_available(), reason="tree-sitter not installed; extractors are unreachable"
)

# 1500 > the default recursion limit of 1000, with margin.
_NESTING = 1500
_OPEN = b"(" * _NESTING
_CLOSE = b")" * _NESTING


def _ast_depth(node) -> int:
    """Measure depth iteratively — the code under test cannot be trusted to."""
    depth, stack = 0, [(node, 1)]
    while stack:
        current, level = stack.pop()
        depth = max(depth, level)
        stack.extend((child, level + 1) for child in current.children)
    return depth


# (language, source, module, entry point). Every source nests inside a field or
# top-level initializer, which is the region the catch-all descent traverses.
_CASES = [
    (
        "java",
        b"class A { int x = " + _OPEN + b"1" + _CLOSE + b"; }",
        "mcp_server.core.ast_extractors_jvm",
        "extract_java_definitions",
    ),
    (
        "kotlin",
        b"class A { val x = " + _OPEN + b"1" + _CLOSE + b" }",
        "mcp_server.core.ast_extractors_jvm",
        "extract_kotlin_definitions",
    ),
    (
        "csharp",
        b"class A { int X = " + _OPEN + b"1" + _CLOSE + b"; }",
        "mcp_server.core.ast_extractors_clike",
        "extract_csharp_definitions",
    ),
    (
        "ruby",
        b"class A\n X = " + _OPEN + b"1" + _CLOSE + b"\nend\n",
        "mcp_server.core.ast_extractors_scripting",
        "extract_ruby_definitions",
    ),
    (
        "php",
        b"<?php $x = " + _OPEN + b"1" + _CLOSE + b";",
        "mcp_server.core.ast_extractors_scripting",
        "extract_php_definitions",
    ),
    (
        "swift",
        b"let x = " + _OPEN + b"1" + _CLOSE,
        "mcp_server.core.ast_extractors_extra",
        "extract_swift_definitions",
    ),
]


@pytest.mark.parametrize(
    ("language", "source", "module", "entry_point"),
    _CASES,
    ids=[case[0] for case in _CASES],
)
def test_extractor_survives_an_ast_deeper_than_the_recursion_limit(
    language: str, source: bytes, module: str, entry_point: str
) -> None:
    from tree_sitter_language_pack import get_parser

    root = get_parser(language).parse(source).root_node

    depth = _ast_depth(root)
    assert depth > sys.getrecursionlimit(), (
        f"{language}: fixture is only {depth} deep against a recursion limit of "
        f"{sys.getrecursionlimit()} — it can no longer reach the defect it guards"
    )

    getattr(importlib.import_module(module), entry_point)(root, source)


def test_call_extraction_survives_a_deep_ast() -> None:
    """`extract_calls_per_function` drives `_walk_for_calls`, the second
    full-tree walker in `ast_extractors` and the one carrying class scope.
    """
    from tree_sitter_language_pack import get_parser

    from mcp_server.core.ast_extractors import extract_calls_per_function

    source = (
        b"class C:\n    def m(self):\n        return " + _OPEN + b"1" + _CLOSE + b"\n"
    )
    root = get_parser("python").parse(source).root_node
    assert _ast_depth(root) > sys.getrecursionlimit()

    out = extract_calls_per_function(root, source)
    assert "C.m" in out, "scope tracking must survive the iterative rewrite"
