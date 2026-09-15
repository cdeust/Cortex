"""Filesystem boundary for core/wiki_coverage.py (issue #560: core/ may
not import os or perform I/O). Wired in via
core.wiki_coverage.configure_wiki_coverage_filesystem —
mcp_server/__main__.py for production, tests_py/conftest.py for the test
session.

source: ADR-0297, issue #560
"""

from __future__ import annotations

import os

from mcp_server.shared.platform import to_posix


def stat_page(wiki_root: str, rel_path: str) -> tuple[int, float] | None:
    """(size_bytes, mtime) of a wiki page, or None if it does not exist.

    source: ADR-0297"""
    full = os.path.join(wiki_root, rel_path)
    try:
        st = os.stat(full)
    except OSError:
        return None
    return st.st_size, st.st_mtime


def markdown_file_sizes(dom_path: str) -> dict[str, int]:
    """``{filename: size_bytes}`` for every ``.md`` file directly under
    ``dom_path``. Empty when the directory does not exist.

    source: ADR-0297"""
    if not os.path.isdir(dom_path):
        return {}
    out: dict[str, int] = {}
    for entry in os.listdir(dom_path):
        if not entry.endswith(".md"):
            continue
        full = os.path.join(dom_path, entry)
        try:
            out[entry] = os.path.getsize(full)
        except OSError:
            continue
    return out


def domain_kind_membership(
    wiki_root: str, known_kinds: frozenset[str]
) -> dict[str, list[str]]:
    """``{candidate_domain_name: [kind, ...]}`` — which of ``known_kinds``'
    directories contain each subdirectory name, for ``list_domains()``'s
    membership count. Empty when ``wiki_root`` does not exist.

    source: ADR-0297"""
    if not os.path.isdir(wiki_root):
        return {}
    memberships: dict[str, list[str]] = {}
    for kind in known_kinds:
        kind_dir = os.path.join(wiki_root, kind)
        if not os.path.isdir(kind_dir):
            continue
        try:
            entries = os.listdir(kind_dir)
        except OSError:
            continue
        for entry in entries:
            if os.path.isdir(os.path.join(kind_dir, entry)):
                memberships.setdefault(entry, []).append(kind)
    return memberships


def walk_source_files(
    root: str, skip_directories: frozenset[str], source_extensions: frozenset[str]
) -> list[str]:
    """Root-relative posix paths of source files under ``root``, skipping
    ``skip_directories`` and dot-directories. Empty when ``root`` does not
    exist.

    source: ADR-0297"""
    if not os.path.isdir(root):
        return []
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if d not in skip_directories and not d.startswith(".")
        ]
        for f in filenames:
            dot = f.rfind(".")
            ext = f[dot:].lower() if dot > 0 else ""
            if ext not in source_extensions:
                continue
            full = os.path.join(dirpath, f)
            out.append(to_posix(os.path.relpath(full, root)))
    return out


def walk_markdown_contents(wiki_root: str) -> list[str]:
    """Text content of every ``.md`` file under ``wiki_root``, skipping
    dot- and underscore-prefixed directories. Empty when ``wiki_root``
    does not exist.

    source: ADR-0297"""
    if not os.path.isdir(wiki_root):
        return []
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(wiki_root):
        dirnames[:] = [
            d for d in dirnames if not d.startswith(".") and not d.startswith("_")
        ]
        for f in filenames:
            if not f.endswith(".md"):
                continue
            full = os.path.join(dirpath, f)
            try:
                with open(full, encoding="utf-8", errors="ignore") as fp:
                    out.append(fp.read())
            except OSError:
                continue
    return out
