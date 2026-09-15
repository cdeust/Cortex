"""Filesystem boundary for core/wiki_drift.py (issue #560: core/ may not
import os or perform I/O). Wired in via
core.wiki_drift.configure_wiki_drift_filesystem — mcp_server/__main__.py
for production, tests_py/conftest.py for the test session.

source: ADR-0301 (issue #560)
"""

from __future__ import annotations

import os
from collections.abc import Iterator

from mcp_server.shared.platform import to_posix
from mcp_server.shared.wiki_skip_directories import SKIP_DIRECTORIES


def read_wiki_page(wiki_root: str, page_rel_path: str) -> str | None:
    """Read one wiki page's raw text, or None if it cannot be read.

    source: ADR-0301"""
    full = os.path.join(wiki_root, page_rel_path)
    try:
        with open(full, encoding="utf-8", errors="ignore") as fp:
            return fp.read()
    except OSError:
        return None


def wiki_page_mtime(wiki_root: str, page_rel_path: str) -> float:
    """Last-modified time of a wiki page, or 0.0 if it cannot be stat'd.

    source: ADR-0301"""
    full = os.path.join(wiki_root, page_rel_path)
    try:
        return os.path.getmtime(full)
    except OSError:
        return 0.0


def source_file_exists_under(source_root: str, cited: str) -> bool:
    """Does ``cited`` resolve to an actual file under ``source_root``,
    directly or (basename fallback) anywhere in its tree?

    source: ADR-0301"""
    full = os.path.join(source_root, cited)
    if os.path.isfile(full):
        return True
    bn = os.path.basename(cited)
    for _dirpath, dirnames, filenames in os.walk(source_root):
        dirnames[:] = [
            d for d in dirnames if d not in SKIP_DIRECTORIES and not d.startswith(".")
        ]
        if bn in filenames:
            return True
    return False


def iter_wiki_markdown_pages(wiki_root: str) -> Iterator[str]:
    """Yield wiki-relative posix paths of every ``.md`` file under
    ``wiki_root`` (skipping dot- and underscore-prefixed directories).
    Yields nothing if ``wiki_root`` does not exist.

    source: ADR-0301"""
    if not os.path.isdir(wiki_root):
        return
    for dirpath, dirnames, filenames in os.walk(wiki_root):
        dirnames[:] = [
            d for d in dirnames if not d.startswith(".") and not d.startswith("_")
        ]
        for f in filenames:
            if f.endswith(".md"):
                full = os.path.join(dirpath, f)
                yield to_posix(os.path.relpath(full, wiki_root))
