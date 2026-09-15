"""Filesystem boundary for core/wiki_axis_registry.py (issue #560: core/
may not import os/pathlib or perform I/O). Wired in via
core.wiki_axis_registry.configure_schema_file_reader —
mcp_server/__main__.py for production, tests_py/conftest.py for the test
session.

source: ADR-0292 (issue #560)
"""

from __future__ import annotations

from pathlib import Path


def read_schema_files(wiki_root: str | None) -> list[tuple[str, str, str]]:
    """Read every ``<wiki_root>/_schema/<axis>/*.md`` file.

    Returns a list of ``(axis_dir_name, file_path, content)`` triples.
    Empty when ``wiki_root`` is None, the schema folder is absent, or an
    axis subdirectory is not actually a directory. A file that cannot be
    read (permissions, encoding) is silently skipped.

    source: ADR-0292"""
    if wiki_root is None:
        return []
    root = Path(wiki_root).expanduser()
    schema_root = root / "_schema"
    if not schema_root.is_dir():
        return []
    out: list[tuple[str, str, str]] = []
    for axis_dir in schema_root.iterdir():
        if not axis_dir.is_dir():
            continue
        for md in axis_dir.glob("*.md"):
            try:
                text = md.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            out.append((axis_dir.name, str(md), text))
    return out
