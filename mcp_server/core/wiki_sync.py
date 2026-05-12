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


# ADR-2244 §4.1: modern kind → directory. All 8 modern kinds map to their
# own directory under wiki/. The classifier never returns a legacy kind
# from v2; legacy directories stay populated only by pre-migration content.
_MODERN_KIND_TO_DIR = {
    "tutorial": "tutorial",
    "how-to": "how-to",
    "reference": "reference",
    "explanation": "explanation",
    "adr": "adr",
    "runbook": "runbook",
    "rfc": "rfc",
    "journal": "journal",
}


def build_from_memory(
    *,
    memory_id: int | str,
    content: str,
    tags: list[str] | None,
    domain: str = "",
) -> tuple[str, str] | None:
    """Build (relative_path, markdown) for a memory, or None if rejected.

    Uses the v2 classifier (ADR-2244) to determine the 4-tuple
    classification, routes to the modern kind directory, and writes
    frontmatter conforming to the new schema.

    Routing fix (Task #8): file-documentation content from
    ``codebase_analyze`` now lands in ``reference/<domain>/`` with
    ``provenance=auto-generated`` instead of being silently dumped in
    ``notes/`` (which had no ``file`` mapping in the old _KIND_TO_DIR).
    """
    classification = classify_memory(content, tags)
    if classification is None:
        return None

    title = derive_title(content, classification.kind, tags)
    if not title:
        import hashlib

        title = f"memory-{hashlib.sha256(content.encode()).hexdigest()[:8]}"

    slug = slugify(title)
    filename = f"{memory_id}-{slug}.md"

    dir_name = _MODERN_KIND_TO_DIR.get(classification.kind, "explanation")
    safe_domain = slugify(domain, max_len=40) if domain else "_general"
    rel = f"{dir_name}/{safe_domain}/{filename}"

    # Frontmatter from the 4-tuple; body from the existing note template.
    fm = classification.to_frontmatter()
    fm["title"] = title
    fm["updated"] = _now_iso()
    if "memory_id" not in fm:
        fm["memory_id"] = memory_id

    markdown = _render_with_frontmatter(fm, title, content)
    return rel, markdown


def _render_with_frontmatter(
    frontmatter: dict[str, object],
    title: str,
    body: str,
) -> str:
    """Render a wiki page with explicit ADR-2244 frontmatter.

    Falls back to ``build_note`` for the body shape so legacy callers
    continue to see a familiar note structure. The frontmatter is the
    only thing that changes — the body remains the existing template
    output until per-kind templates land in Phase 1.D.
    """
    # Use the existing note builder for the body shape, then replace its
    # frontmatter with the 4-tuple-aware version.
    note_md = build_note(
        title=title,
        body=body,
        tags=list(frontmatter.get("tags") or []),
        updated=str(frontmatter.get("updated", "")),
    )
    body_only = _strip_frontmatter(note_md)
    return _format_frontmatter(frontmatter) + body_only


def _strip_frontmatter(md: str) -> str:
    """Remove a leading ``---``-delimited frontmatter block from markdown."""
    if not md.startswith("---"):
        return md
    end = md.find("\n---", 3)
    if end == -1:
        return md
    body_start = md.find("\n", end + 4)
    return md[body_start + 1 :] if body_start != -1 else ""


def _format_frontmatter(fm: dict[str, object]) -> str:
    """Serialise a frontmatter dict to a ``---``-delimited YAML block.

    Mirrors wiki_pages._format_frontmatter but lives here so wiki_sync
    can produce ADR-2244 frontmatter without importing from wiki_pages
    (whose builder API does not accept arbitrary dicts).
    """
    lines = ["---"]
    for key, value in fm.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        elif isinstance(value, dict):
            lines.append(f"{key}:")
            for sub_key, sub_value in value.items():
                lines.append(f"  {sub_key}: {sub_value}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)
