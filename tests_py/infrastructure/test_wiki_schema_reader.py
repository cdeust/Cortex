"""Tests for the infrastructure-side wiki schema reader (issue #126 split).

``mcp_server.shared.wiki_schema_loader`` declares the pure data model and
parsers; ``mcp_server.infrastructure.wiki_schema_reader`` is the I/O
adapter that walks a wiki root on disk and builds a ``WikiRegistry`` from
it. These tests exercise the adapter end-to-end against a temp directory,
verifying it produces the same shape the pre-split single-file module did.
"""

from __future__ import annotations

from pathlib import Path

from mcp_server.infrastructure.wiki_schema_reader import load_registry


def test_load_registry_on_missing_wiki_root_returns_empty(tmp_path: Path) -> None:
    registry = load_registry(tmp_path / "does-not-exist")
    assert registry.kinds == {}
    assert registry.rules == []
    assert registry.views == {}
    assert registry.triggers == {}


def test_load_registry_parses_kind_definition(tmp_path: Path) -> None:
    kinds_dir = tmp_path / "_kinds"
    kinds_dir.mkdir(parents=True)
    (kinds_dir / "adr.md").write_text(
        "---\nname: adr\ndisplay_name: ADR\ndir_name: adr\n"
        "required_sections:\n  - Decision\n  - Consequences\n---\n"
    )
    registry = load_registry(tmp_path)
    assert "adr" in registry.kinds
    assert registry.kinds["adr"].display_name == "ADR"
    assert registry.kinds["adr"].required_sections == ["Decision", "Consequences"]


def test_load_registry_parses_rules_table(tmp_path: Path) -> None:
    rules_dir = tmp_path / "_rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "default.md").write_text(
        "---\nname: default\n---\n\n"
        "| pattern | kind | target | weight | note |\n"
        "|---|---|---|---|---|\n"
        "| decision: | prefix | adr | 1.0 | |\n"
    )
    registry = load_registry(tmp_path)
    assert len(registry.rules) == 1
    assert registry.rules[0].target_kind == "adr"


def test_load_registry_parses_view_definition(tmp_path: Path) -> None:
    views_dir = tmp_path / "_views"
    views_dir.mkdir(parents=True)
    (views_dir / "open-questions.md").write_text(
        "---\nname: open-questions\n---\n\n"
        "```cortex-query\ntable: pages\nlimit: 5\n```\n"
    )
    registry = load_registry(tmp_path)
    assert "open-questions" in registry.views
    assert "limit: 5" in registry.views["open-questions"].query
