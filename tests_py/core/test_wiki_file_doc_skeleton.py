"""Tests for core/wiki_file_doc_skeleton — curation-gap-exposing skeletons.

The module's contract (docstring + user direction 2026-05-18): a
generated file-doc declares EVERY canonical section, fills what it can
extract mechanically (language, imports, public symbols), and marks the
rest with an explicit ``_(missing — needs: …)_`` marker that is
distinguishable from the purge-targeted stub markers. These tests pin
that observable page shape, not the extraction internals.
"""

from __future__ import annotations

from mcp_server.core.wiki_curation_gaps import FILE_DOC_SECTIONS
from mcp_server.core.wiki_file_doc_skeleton import (
    _detect_language,
    _extract_imports,
    _extract_symbols,
    build_file_doc,
)

_TODAY = "2026-07-28"


# ── Language detection ────────────────────────────────────────────────


def test_known_extensions_map_to_their_language():
    assert _detect_language("pkg/mod.py") == "python"
    assert _detect_language("src/App.tsx") == "typescript"
    assert _detect_language("lib/main.rs") == "rust"
    assert _detect_language("Query.SQL") == "sql", "extension match is case-insensitive"


def test_unknown_extension_degrades_to_text():
    assert _detect_language("README") == "text"
    assert _detect_language("notes.xyz") == "text"


# ── Import extraction ─────────────────────────────────────────────────


def test_python_imports_are_extracted_from_both_forms():
    src = "import os\nfrom pathlib import Path\nx = 1\n"
    assert _extract_imports("python", src) == ["os", "pathlib"]


def test_typescript_imports_use_the_module_specifier():
    src = 'import { useState } from "react"\nconst x = 1\n'
    assert _extract_imports("typescript", src) == ["react"]


def test_imports_are_deduped_and_capped_at_twenty():
    src = "\n".join(f"import mod{i % 30}" for i in range(60))
    imports = _extract_imports("python", src)
    assert len(imports) == len(set(imports))
    assert len(imports) == 20


def test_imports_beyond_the_first_200_lines_are_ignored():
    src = ("x = 1\n" * 200) + "import late_module\n"
    assert _extract_imports("python", src) == []


def test_non_code_language_yields_no_imports():
    assert _extract_imports("text", "import os\n") == []


# ── Symbol extraction ─────────────────────────────────────────────────


def test_python_top_level_defs_and_classes_are_extracted():
    src = (
        "def alpha():\n    def nested():\n        pass\n"
        "class Beta:\n    pass\nasync def gamma():\n    pass\n"
    )
    assert _extract_symbols("python", src) == ["alpha", "Beta", "gamma"]


def test_private_symbols_are_filtered_out():
    src = "def _internal():\n    pass\ndef public():\n    pass\n"
    assert _extract_symbols("python", src) == ["public"]


def test_typescript_exports_are_extracted():
    src = "export function render() {}\nexport class Store {}\nconst hidden = 1\n"
    assert _extract_symbols("typescript", src) == ["render", "Store"]


# ── Page shape ────────────────────────────────────────────────────────


def _build(source: str = "", path: str = "pkg/mod.py") -> str:
    return build_file_doc(path, source, "cortex", today=_TODAY)


def test_frontmatter_carries_identity_lifecycle_and_dates():
    page = _build("import os\n")
    assert page.startswith("---\n")
    assert "title: File: pkg/mod.py\n" in page
    assert "domain: cortex\n" in page
    assert "language: python\n" in page
    assert "lifecycle: needs-curation\n" in page
    assert "provenance: skeleton\n" in page
    assert f"created: {_TODAY}\n" in page
    assert "  - lang:python" in page
    assert "  - file:pkg/mod.py" in page
    assert "  - domain:cortex" in page
    assert "  - codebase-skeleton" in page


def test_every_canonical_section_heading_is_present():
    page = _build()
    for section in FILE_DOC_SECTIONS:
        assert section.heading in page, f"missing heading {section.heading}"
    assert "## See also" in page


def test_empty_source_marks_every_section_as_a_gap():
    page = _build("")
    for section in FILE_DOC_SECTIONS:
        assert f"  - {section.name}" in page, "each gap listed in frontmatter"
    assert page.count("_(missing — needs:") >= len(FILE_DOC_SECTIONS)


def test_extracted_imports_populate_dependencies_and_clear_that_gap():
    page = _build("from pathlib import Path\n")
    assert "* `pathlib`" in page
    dep_section = next(s for s in FILE_DOC_SECTIONS if s.name == "dependencies")
    assert f"  - {dep_section.name}\n" not in page, "dependencies is no longer a gap"


def test_extracted_symbols_populate_public_api_with_per_symbol_markers():
    page = _build("def handler():\n    pass\n")
    assert "* `handler` — _(missing — needs: one-line semantic)_" in page
    api_section = next(s for s in FILE_DOC_SECTIONS if s.name == "public-api")
    assert f"  - {api_section.name}\n" not in page


def test_line_count_is_reported():
    page = _build("a = 1\nb = 2\n")
    assert "line_count: 3\n" in page, "count('\\n') + 1 convention"
    assert "_Line count_: **3**" in page


def test_markers_are_distinct_from_purge_targeted_stub_markers():
    page = _build("")
    assert "_(to be filled)_" not in page
    assert "_To be written._" not in page
