"""Filesystem adapter for ``core.auto_curator``'s ``WikiPagePort`` (issue #314).

``core/auto_curator.py``'s module docstring states "Pure business logic —
no I/O", but it used to perform direct ``os``/``pathlib`` filesystem
calls (mtime freshness check + page-content read) — a layer violation of
docs/module-inventory.md's dependency rule ("core/ ... Must NOT Import:
... os/pathlib"). This module is where that concrete I/O now lives,
behind the ``WikiPagePort`` protocol core declares. Reverse DI
(coding-standards.md §5.1/§5.2): core declares the shape of the
dependency it needs; this adapter implements it; the handler-level
composition roots (``handlers/curate_wiki.py``,
``handlers/consolidation/wiki_backlog_pass.py``,
``hooks/session_start.py``) construct it via ``build_wiki_page_port`` and
inject the instance.

This module intentionally does NOT import ``core.auto_curator`` — Python
Protocols are structurally typed (PEP 544): a class satisfies a Protocol
by matching its method shapes, no inheritance or import required. That
also keeps this file compliant with docs/module-inventory.md's
infrastructure/ dependency rule, which forbids infrastructure/ importing
core/.
"""

from __future__ import annotations

import os
import time


class FsWikiPagePort:
    """os/pathlib-backed ``WikiPagePort``, bound to one wiki root.

    Preserves the exact pre-refactor semantics of the two call sites this
    replaces in ``core/auto_curator.py`` (behaviour-preserving move, issue
    #314): ``is_recently_modified`` is the same
    ``os.path.isfile`` + ``time.time() - os.path.getmtime`` check that
    used to live in ``is_path_recently_authored``; ``read_text`` is the
    same naive ``os.path.join`` + ``open(..., errors="ignore")`` +
    catch-``OSError``-and-skip read that used to live in
    ``build_reauthor_jobs``. Both call sites' inputs come from the
    system's own suggested/drift paths, not untrusted external input, so
    no additional path-traversal hardening was added here — that would be
    a behaviour change, out of scope for this refactor (see
    ``infrastructure/wiki_store.py::read_page`` for the CWE-22-hardened
    variant used where the input is untrusted).
    """

    def __init__(self, wiki_root: str) -> None:
        self._wiki_root = wiki_root

    def is_recently_modified(self, rel_path: str, within_days: int) -> bool:
        """True if ``<wiki_root>/<rel_path>`` exists and was modified
        within the last ``within_days`` days."""
        full = os.path.join(self._wiki_root, rel_path)
        if not os.path.isfile(full):
            return False
        age_seconds = time.time() - os.path.getmtime(full)
        return age_seconds < (within_days * 86400)

    def read_text(self, rel_path: str) -> str | None:
        """Return ``<wiki_root>/<rel_path>``'s raw text, or ``None`` if
        the file is missing or can't be read."""
        full = os.path.join(self._wiki_root, rel_path)
        try:
            # source: mutation run 2026-07-31 (scripts/mutation_check.sh),
            # tests_py/infrastructure/test_wiki_page_fs.py — 28/31 mutants
            # killed. 3 accepted-equivalent survivors on `encoding="utf-8"`:
            # dropping it or passing `encoding=None` is unkillable in this
            # repo's supported environments (every CI runner and documented
            # dev setup runs a UTF-8 locale, verified empirically —
            # monkeypatching `locale.getencoding`/`getpreferredencoding`
            # does not change what a bare `open()` resolves to on this
            # platform, so the explicit arg is redundant-but-harmless
            # here); `encoding="UTF-8"` is a true equivalent always (codec
            # names are case/dash-insensitive in Python's codec registry).
            with open(full, encoding="utf-8", errors="ignore") as fp:
                return fp.read()
        except OSError:
            return None


def build_wiki_page_port(wiki_root: str) -> FsWikiPagePort:
    """Factory — composition roots call this to wire the port (§5.2)."""
    return FsWikiPagePort(wiki_root)
