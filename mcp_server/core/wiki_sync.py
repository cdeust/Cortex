"""Wiki sync — decide whether a stored memory should be promoted to an
authored wiki page, and build the page payload.

source: ADR-0314"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from mcp_server.core.wiki_classifier import classify_memory, derive_title
from mcp_server.core.wiki_identity import generate_page_id
from mcp_server.shared.wiki_layout import slugify
from mcp_server.shared.wiki_pages import build_note
from mcp_server.shared.wiki_classification import classification_to_frontmatter
from mcp_server.shared.wiki_page_candidate import PageCandidate
from mcp_server.shared.wiki_pointer import is_pointer_source
import hashlib

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
    # source: ADR-0314
    for prefix in ("Decision:", "Rule:", "Lesson:", "Note:"):
        if first_line.startswith(prefix):
            first_line = first_line[len(prefix) :].strip()
            break
    if len(first_line) > _TITLE_MAX_LEN:
        first_line = first_line[:_TITLE_MAX_LEN].rsplit(" ", 1)[0] + "…"
    return first_line


# source: ADR-0314


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


def _page_frontmatter(
    classification, title: str, memory_id: int | str
) -> dict[str, object]:
    """The 4-tuple axes plus page identity, ready to serialise.

    source: ADR-0314"""
    fm = classification_to_frontmatter(classification)
    fm["id"] = generate_page_id()
    fm["title"] = title
    fm["updated"] = _now_iso()
    if "memory_id" not in fm:
        fm["memory_id"] = memory_id
    return fm


def build_from_memory(candidate: PageCandidate) -> tuple[str, str] | None:
    """Build (relative_path, markdown) for a memory, or None if rejected.

    This is the first pass that admits a memory into wiki
    materialisation, so it is where a memory that is itself a pointer at
    an already-authored page is turned away: materialising one rebuilds
    a corrupted copy of the page it points at (issue #622).
    ``PageCandidate.memory_source`` has no default, so a new call site
    cannot reopen that loop by omitting it.

    source: ADR-0314"""
    if is_pointer_source(candidate.memory_source):
        return None

    content, tags = candidate.content, candidate.tags
    classification = classify_memory(content, tags)
    if classification is None:
        return None

    title = derive_title(content, classification.kind, tags)
    if not title:
        title = f"memory-{hashlib.sha256(content.encode()).hexdigest()[:8]}"

    dir_name = _MODERN_KIND_TO_DIR.get(classification.kind, "explanation")
    domain = candidate.domain
    safe_domain = slugify(domain, max_len=40) if domain else "_general"
    rel = f"{dir_name}/{safe_domain}/{candidate.memory_id}-{slugify(title)}.md"

    # source: ADR-0314
    fm = _page_frontmatter(classification, title, candidate.memory_id)
    return rel, _render_with_frontmatter(fm, title, content)


def _render_with_frontmatter(
    frontmatter: dict[str, object],
    title: str,
    body: str,
) -> str:
    """Render a wiki page with explicit classification frontmatter.

    source: ADR-0314
    """
    # source: ADR-0314

    raw_tags = frontmatter.get("tags")
    note_md = build_note(
        title=title,
        body=body,
        tags=[str(t) for t in raw_tags] if isinstance(raw_tags, list) else [],
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

    source: ADR-0314"""
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
