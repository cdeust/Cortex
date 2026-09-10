"""source: ADR-0626"""

from __future__ import annotations

import os
import time


class FsWikiPagePort:
    """os/pathlib-backed ``WikiPagePort``, bound to one wiki root.

    source: ADR-0626"""

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
            # source: ADR-0626
            with open(full, encoding="utf-8", errors="ignore") as fp:
                return fp.read()
        except OSError:
            return None


def build_wiki_page_port(wiki_root: str) -> FsWikiPagePort:
    """Factory — composition roots call this to wire the port (§5.2)."""
    return FsWikiPagePort(wiki_root)
