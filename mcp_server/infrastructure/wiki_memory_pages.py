"""Wiki page files that are copies of one memory's text (hard forget).

Two writers copy a memory into the wiki tree: promotion
(``handlers/wiki_memory_sync``, a page named ``<memory_id>-<slug>.md`` with
``memory_id: <id>`` in its front matter) and compilation of a draft (a
``wiki.pages`` row whose ``memory_id`` is the memory; the store returns its
``rel_path``). Both are removed when the memory is hard-forgotten, then the
index is rebuilt so no listing keeps the page title.

source: ADR-1111"""

from __future__ import annotations

import re
from pathlib import Path

from mcp_server.infrastructure import wiki_reindex_io

# source: ADR-1111 — front matter is in the first lines of a page
_HEAD_BYTES = 4096


def _declares_memory(path: Path, memory_id: int) -> bool:
    with path.open("rb") as stream:
        head = stream.read(_HEAD_BYTES).decode("utf-8", "replace")
    pattern = rf"(?m)^memory_id:\s*['\"]?{memory_id}['\"]?\s*$"
    return head.startswith("---") and re.search(pattern, head) is not None


def derived_page_files(root: Path, memory_id: int, rel_paths: list[str]) -> list[Path]:
    """Existing page files under ``root`` that copy ``memory_id``."""
    if not root.is_dir():
        return []
    base = root.resolve()
    found = {base / rel for rel in rel_paths}
    found |= {
        p for p in base.rglob(f"{memory_id}-*.md") if _declares_memory(p, memory_id)
    }
    return sorted(p for p in found if p.is_file() and base in p.resolve().parents)


def remove_derived_pages(root: Path, memory_id: int, rel_paths: list[str]) -> int:
    """Delete the page files copying ``memory_id``; return how many."""
    files = derived_page_files(root, memory_id, rel_paths)
    for path in files:
        path.unlink()
    if files:
        wiki_reindex_io.reindex(root)
    return len(files)
