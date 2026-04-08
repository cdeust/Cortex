"""Wiki sync — decide whether a stored memory should be promoted to an
authored wiki page, and build the page payload.

Pure logic, no I/O. The caller (infrastructure/wiki_store.py::sync_memory)
is responsible for writing the returned markdown to disk.

Design intent
-------------
The wiki is an *authored* layer, not a projection of every memory. Only
memories tagged with a "decision-shaped" tag (decision, adr, architecture,
spec, design) are promoted. The promotion produces a ``note``-kind page
per memory: the ADR / spec structured templates stay reserved for
explicit `wiki_adr` / `wiki_write` tool calls where the caller supplies
the structure.

Filename format: ``notes/<memory_id>-<slug>.md``. Including the memory ID
in the filename makes sync idempotent — a second call with the same
memory ID overwrites the same file rather than creating duplicates.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from mcp_server.core.wiki_layout import page_path, slugify
from mcp_server.core.wiki_pages import build_note

_DECISION_TAGS = frozenset({"decision", "adr", "architecture", "spec", "design"})
_TITLE_MAX_LEN = 80


def should_sync(tags: list[str] | None) -> bool:
    """True if the memory's tags warrant a wiki page."""
    if not tags:
        return False
    return any(t.lower() in _DECISION_TAGS for t in tags)


def _derive_title(content: str) -> str:
    """Extract a short title from the first line or sentence of content."""
    if not content:
        return "untitled memory"
    first_line = content.strip().splitlines()[0].strip()
    # Strip common prefixes like "Decision:" or "Rule:".
    for prefix in ("Decision:", "Rule:", "Lesson:", "Note:"):
        if first_line.startswith(prefix):
            first_line = first_line[len(prefix) :].strip()
            break
    if len(first_line) > _TITLE_MAX_LEN:
        first_line = first_line[:_TITLE_MAX_LEN].rsplit(" ", 1)[0] + "…"
    return first_line or "untitled memory"


def build_from_memory(
    *,
    memory_id: int | str,
    content: str,
    tags: list[str] | None,
) -> tuple[str, str] | None:
    """Build (relative_path, markdown) for a memory, or None if not syncable.

    The relative path is POSIX-style (forward slashes) rooted at the wiki
    root; the caller joins it with the concrete root directory.
    """
    if not should_sync(tags):
        return None
    title = _derive_title(content)
    slug = slugify(title)
    filename = f"{memory_id}-{slug}.md"
    rel = page_path("notes", filename)
    markdown = build_note(title=title, body=content, tags=tags or ["note"])
    return str(PurePosixPath(rel)), markdown
