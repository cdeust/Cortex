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

import re
from datetime import datetime, timezone

from mcp_server.core.wiki_classifier import classify_memory, derive_title
from mcp_server.core.wiki_layout import slugify
from mcp_server.core.wiki_pages import build_note

_DECISION_TAGS = frozenset({"decision", "adr", "architecture", "spec", "design"})


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_TITLE_MAX_LEN = 80


def should_sync(tags: list[str] | None) -> bool:
    """True if the memory's tags warrant a wiki page."""
    if not tags:
        return False
    return any(t.lower() in _DECISION_TAGS for t in tags)


def _derive_title(content: str) -> str:
    """Extract a short title from the first line or sentence of content.

    Returns ``""`` when no usable title can be derived.
    """
    if not content:
        return ""
    first_line = content.strip().splitlines()[0].strip()
    # Strip markdown heading prefixes (## , ### , etc.).
    first_line = re.sub(r"^#+\s*", "", first_line)
    # Strip common prefixes like "Decision:" or "Rule:".
    for prefix in ("Decision:", "Rule:", "Lesson:", "Note:"):
        if first_line.startswith(prefix):
            first_line = first_line[len(prefix) :].strip()
            break
    if len(first_line) > _TITLE_MAX_LEN:
        first_line = first_line[:_TITLE_MAX_LEN].rsplit(" ", 1)[0] + "…"
    return first_line


def build_from_memory(
    *,
    memory_id: int | str,
    content: str,
    tags: list[str] | None,
    domain: str = "",
) -> tuple[str, str] | None:
    """Build (relative_path, markdown) for a memory, or None if rejected.

    Uses the wiki classifier to determine page kind and smart title.
    Routes to kind-specific templates. Domain-scoped paths.
    """
    # Use classifier instead of tag-only gate
    kind = classify_memory(content, tags)
    if kind is None:
        return None

    title = derive_title(content, kind, tags)
    if not title:
        import hashlib

        title = f"memory-{hashlib.sha256(content.encode()).hexdigest()[:8]}"

    slug = slugify(title)
    filename = f"{memory_id}-{slug}.md"

    # Map classifier kind (singular) to PAGE_KINDS directory (plural)
    _KIND_TO_DIR = {
        "adr": "adr",
        "spec": "specs",
        "lesson": "lessons",
        "convention": "conventions",
        "note": "notes",
        "guide": "guides",
        "reference": "reference",
        "journal": "journal",
    }
    dir_name = _KIND_TO_DIR.get(kind, "notes")
    safe_domain = slugify(domain, max_len=40) if domain else "_general"
    rel = f"{dir_name}/{safe_domain}/{filename}"

    # Build page with kind-appropriate template
    markdown = build_note(
        title=title, body=content, tags=tags or [kind], updated=_now_iso()
    )
    return rel, markdown
