"""The AST_SUPPORTED ↔ tree-sitter-language-pack contract (issue #253).

`ast_parser` declares `AST_SUPPORTED` as the pack's own `SupportedLanguage`
literal and hands its members straight to `get_parser`. That declaration is
checked statically by pyright against whichever pack version the environment
resolved — which is exactly the thing that differed between CI and a
range-resolved developer install, and it is only as good as the environment
running the checker.

These tests pin the same contract at runtime, in every environment the suite
runs in: each name in `AST_SUPPORTED` must be one the installed pack both
types (`get_args(SupportedLanguage)`) and accepts (`get_parser`). A pack whose
literal drops a name — `tree-sitter-language-pack<=1.6.2` shipped a
179-name literal without `csharp`, measured 2026-07-29 — fails here rather
than in a contributor's type checker.
"""

from __future__ import annotations

import sys
from typing import get_args

import pytest

from mcp_server.core import ast_parser
from mcp_server.core.ast_parser import (
    AST_SUPPORTED,
    _get_extractor_and_tree,
    _is_ast_language,
    is_available,
    parse_file_ast,
)

pytestmark = pytest.mark.skipif(not is_available(), reason="tree-sitter not installed")


def test_every_supported_name_is_typed_by_the_installed_pack() -> None:
    from tree_sitter_language_pack import SupportedLanguage

    typed = set(get_args(SupportedLanguage))
    assert typed, "the pack exports SupportedLanguage as an empty literal"
    assert not (set(AST_SUPPORTED) - typed)


def test_every_supported_name_parses_bytes() -> None:
    """The whole call chain `ast_parser` uses, against the installed pack.

    `parse(b"")` and not `parse("")`: 1.9.0-1.12.2 returned a
    `builtins.Parser` whose `parse(source: str)` raises
    `TypeError: 'bytes' object is not an instance of 'str'` — uncaught in
    `_get_extractor_and_tree`, so `codebase_analyze` crashed on any file.
    That window is excluded by the pin; this asserts it stays excluded.
    """
    from tree_sitter_language_pack import get_parser

    for language in sorted(AST_SUPPORTED):
        assert get_parser(language).parse(b"") is not None


def test_is_ast_language_accepts_every_declared_name() -> None:
    for language in sorted(AST_SUPPORTED):
        assert _is_ast_language(language) is True


@pytest.mark.parametrize("language", ["", "cobol", "Python", "text"])
def test_is_ast_language_rejects_names_outside_the_set(language: str) -> None:
    assert language not in AST_SUPPORTED
    assert _is_ast_language(language) is False


def test_unsupported_language_falls_back_before_touching_the_pack() -> None:
    assert _get_extractor_and_tree("cobol", b"IDENTIFICATION DIVISION.") is None


def test_supported_set_is_exactly_the_extractor_table() -> None:
    """`_EXTRACTORS[language]` is total because the set is derived from it.

    Equality, not inclusion: a name in the set with no extractor would make
    that lookup raise KeyError instead of falling back to the regex parser.
    """
    assert set(AST_SUPPORTED) == set(ast_parser._EXTRACTORS)


def test_is_available_is_true_when_the_pack_imports() -> None:
    assert is_available() is True


def test_is_available_is_false_when_the_pack_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`None` in sys.modules makes the import raise ImportError — the exact
    degraded mode of an install without the `codebase` extra."""
    monkeypatch.setitem(sys.modules, "tree_sitter_language_pack", None)
    assert is_available() is False


def test_missing_pack_falls_back_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "tree_sitter_language_pack", None)
    assert _get_extractor_and_tree("python", b"def f():\n    pass\n") is None


# ── DownloadError: the pack imports fine but can't fetch the grammar ──────
#
# Reached a different way than the two tests above: `tree-sitter-language-
# pack` resolves a grammar lazily over the network at `get_parser()` call
# time (not at import time), so an offline install, an air-gapped network,
# a proxy, or an upstream outage raises `DownloadError` from an installed
# pack instead of `ImportError` from a missing one. Forced deterministically
# here (`monkeypatch.setattr` on the pack's own `get_parser`) rather than by
# disabling real network, per CI run 30592244731 (2026-07-31, main) where
# this exact exception escaped `_get_extractor_and_tree` uncaught.


def _make_download_error_parser(message: str):
    """A `get_parser` replacement that always raises `DownloadError`."""
    from tree_sitter_language_pack import DownloadError

    def _raise(_name: str) -> None:
        raise DownloadError(message)

    return _raise


def test_download_error_falls_back_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tree_sitter_language_pack as tslp

    monkeypatch.setattr(
        tslp, "get_parser", _make_download_error_parser("Failed to fetch manifest")
    )
    assert _get_extractor_and_tree("python", b"def f():\n    pass\n") is None


def test_download_error_logs_language_and_reason(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The signal itself is asserted, not just the absence of a crash
    (coding-standards.md §13.1 F1): an operator must be able to tell which
    language failed and why from the log alone."""
    import tree_sitter_language_pack as tslp

    monkeypatch.setattr(
        tslp,
        "get_parser",
        _make_download_error_parser(
            "Failed to fetch manifest from https://example.invalid"
        ),
    )
    with caplog.at_level("WARNING", logger="mcp_server.core.ast_parser"):
        result = _get_extractor_and_tree("python", b"def f():\n    pass\n")
    assert result is None
    # Pins the message's static wording (both halves), not just the
    # dynamic language/reason substitutions — a wording change that drops
    # either half would otherwise still pass on the substrings alone.
    assert any(
        rec.message == "tree-sitter grammar for 'python' could not be obtained "
        "(Failed to fetch manifest from https://example.invalid); "
        "falling back to the regex parser for this file."
        for rec in caplog.records
    )


def test_download_error_degrades_through_parse_file_ast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public entry point `codebase_analyze` calls: never propagates
    the third-party exception, and still returns the same valid
    `FileAnalysis` shape the regex fallback produces for a missing
    install."""
    import tree_sitter_language_pack as tslp

    monkeypatch.setattr(
        tslp, "get_parser", _make_download_error_parser("Failed to fetch manifest")
    )
    result = parse_file_ast("demo.py", b"def f():\n    pass\n")
    assert result.path == "demo.py"
    assert result.language == "python"
    assert isinstance(result.definitions, list)


def test_supported_language_with_an_extractor_parses() -> None:
    result = _get_extractor_and_tree("python", b"def f():\n    pass\n")
    assert result is not None
    extractor, tree = result
    assert callable(extractor)
    assert tree.root_node.type == "module"
