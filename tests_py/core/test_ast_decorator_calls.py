"""Exact decorator call attribution and resolved graph contracts."""

from __future__ import annotations

import pytest

from mcp_server.core.ast_extractors import extract_calls_per_function
from mcp_server.core.ast_parser import is_available, parse_file_ast
from mcp_server.core.codebase_graph import build_resolved_call_edges

pytestmark = pytest.mark.skipif(not is_available(), reason="tree-sitter unavailable")


def _calls(source: bytes) -> dict[str, list[str]]:
    from tree_sitter_language_pack import get_parser

    root = get_parser("python").parse(source).root_node
    assert not root.has_error
    return extract_calls_per_function(root, source)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (b"@property\ndef f():\n    work()\n", {"f": ["work"]}),
        (b"@app.route('/api')\ndef f():\n    work()\n", {"f": ["route", "work"]}),
        (
            b"@outer()\n@inner(option=configure())\ndef f():\n    work()\n",
            {"f": ["outer", "inner", "configure", "work"]},
        ),
        (
            b"class C:\n    @app.route('/')\n    def f(self):\n        work()\n",
            {"C.f": ["route", "work"]},
        ),
        (
            b"@register()\nclass C:\n    initialize()\n"
            b"    def f(self):\n        work()\n",
            {"C": ["register"], "C.f": ["work"]},
        ),
        (b"@register\nclass C:\n    pass\n", {}),
        (
            b"@repeat()\n@repeat()\n@other()\ndef f():\n    repeat()\n    work()\n",
            {"f": ["repeat", "other", "work"]},
        ),
        (
            b"@a.b.deep()\nasync def f(x=default()):\n    await work()\n",
            {"f": ["deep", "work"]},
        ),
        (
            b"class Outer:\n    @register()\n    class Inner:\n"
            b"        @route()\n        def f(self):\n            work()\n",
            {"Inner": ["register"], "Inner.f": ["route", "work"]},
        ),
        (
            b"@old()\ndef f():\n    first()\ndef f():\n    second()\n",
            {"f": ["second"]},
        ),
        (
            b"@register()\nclass C:\n    def f(self):\n        work()\n"
            b"def after():\n    done()\n",
            {"C": ["register"], "C.f": ["work"], "after": ["done"]},
        ),
    ],
    ids=[
        "bare",
        "single",
        "stacked",
        "method",
        "class",
        "bare-class",
        "dedupe",
        "async-default-excluded",
        "nested-class",
        "redefinition",
        "sibling-scope",
    ],
)
def test_decorator_call_attribution(
    source: bytes, expected: dict[str, list[str]]
) -> None:
    got = _calls(source)
    assert got == expected
    assert list(got) == list(expected)


def test_nested_decorated_definition_keeps_existing_enclosing_body_coverage() -> None:
    assert _calls(
        b"def outer():\n    @register()\n    def inner():\n        work()\n"
    ) == {"outer": ["register", "work"], "inner": ["register", "work"]}


def test_bare_decorators_keep_definitions_and_class_names() -> None:
    analysis = parse_file_ast(
        "app.py", b"@bare\nclass C:\n    @property\n    def f(self):\n        pass\n"
    )
    assert [(d.name, d.kind) for d in analysis.definitions] == [
        ("C", "class"),
        ("C.f", "method"),
    ]


def test_reindexed_resolved_edges_include_function_method_and_class_registrations() -> (
    None
):
    sources = {
        "registry.py": b"def route(): pass\ndef register(): pass\ndef work(): pass\n",
        "app.py": (
            b"@route()\ndef handler():\n    work()\n"
            b"@register()\nclass C:\n    @route()\n"
            b"    def method(self):\n        work()\n"
        ),
    }
    analyses = [parse_file_ast(path, body) for path, body in sources.items()]
    assert build_resolved_call_edges(analyses) == [
        ("app.py", "handler", "registry.py", "route"),
        ("app.py", "handler", "registry.py", "work"),
        ("app.py", "C", "registry.py", "register"),
        ("app.py", "C.method", "registry.py", "route"),
        ("app.py", "C.method", "registry.py", "work"),
    ]


def test_call_collector_keeps_its_deduplication_contract() -> None:
    from tree_sitter_language_pack import get_parser

    from mcp_server.core.ast_extractors import _collect_call_basenames

    source = b"work(); work(); other(); work()"
    root = get_parser("python").parse(source).root_node
    assert _collect_call_basenames(root, source) == ["work", "other"]
