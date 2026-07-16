"""Wiki page title derivation — pure text transform, no I/O.

Extracted from ``wiki_classifier.py`` (issue #134, file exceeded the
500-line hard limit in coding-standards.md §4). Deriving a title is a
distinct concern from classifying content into a kind: it only needs
the content, the already-decided kind, and optionally tags/entities.
"""

from __future__ import annotations

import re

from mcp_server.core.wiki_classifier_patterns import (
    PATH_OR_URL_TITLE_PATTERNS,
    YAML_KV_TITLE_PATTERNS,
)

# ── Title prefix stripping ────────────────────────────────────────────

_TITLE_STRIP_PREFIXES = [
    re.compile(r"^#+\s*"),  # Markdown headings
    re.compile(
        r"^(Tool|System|Rule|Decision|Convention|Lesson|Note):\s*", re.IGNORECASE
    ),
    re.compile(r"^Implement the following plan:?\s*", re.IGNORECASE),
    re.compile(r"^Execute the following:?\s*", re.IGNORECASE),
    re.compile(r"^(Here is|Here's|The following)\s+", re.IGNORECASE),
]

# 2026-05-17: markdown unwrappers. Applied with ``sub(r"\1", ...)`` (keep
# inner text) before the path-detection patterns so a line like
# ``**File:** `/Users/.../remember.py` `` is tested against the path
# detector as ``File: /Users/.../remember.py`` — previously the backtick
# before ``/Users/`` wasn't whitespace so the path filter missed and the
# raw markdown-wrapped path leaked into the wiki page title.
_TITLE_MARKDOWN_UNWRAP = [
    re.compile(r"\*\*([^*]+)\*\*"),  # **bold** → bold
    re.compile(r"`([^`]+)`"),  # `code` → code
    re.compile(r"\*([^*]+)\*"),  # *italic* → italic
    re.compile(r"_([^_]+)_"),  # _italic_ → italic
]


def _line_is_title_candidate(cleaned: str) -> bool:
    """Return True iff ``cleaned`` is acceptable as a wiki page title.

    Rejects: empty/short, JSON braces, embedded paths/URLs, YAML metadata
    key:value lines, bare timestamps. Callers that get False from every
    candidate line should yield an empty title and let the deterministic
    hash fallback kick in (see ``wiki_sync._sync_to_wiki``).
    """
    if len(cleaned) <= 10:
        return False
    if cleaned.startswith("{") or cleaned.startswith("["):
        return False
    for pat in PATH_OR_URL_TITLE_PATTERNS:
        if pat.search(cleaned):
            return False
    for pat in YAML_KV_TITLE_PATTERNS:
        if pat.search(cleaned):
            return False
    return True


def derive_title(
    content: str,
    kind: str,
    tags: list[str] | None = None,
    entities: list[str] | None = None,
) -> str:
    """Derive a meaningful title for a wiki page.

    Strategy (inspired by Alexander pattern-language P4 + Eco; framing only):
    1. Strip known prefixes
    2. Walk lines; accept the first that passes ``_line_is_title_candidate``
    3. Fall back to entity-based title if 2+ entities are supplied
    4. Otherwise return "" — caller is responsible for a deterministic
       fallback (e.g. ``memory-<hash>``). Returning a raw 80-char content
       prefix here used to leak filesystem paths, timestamps, and sentence
       fragments into slugs.
    """
    lines = content.strip().split("\n")
    first_meaningful = ""
    for line in lines:
        cleaned = line.strip()
        # Unwrap markdown formatting first so the underlying text is
        # what gets prefix-stripped and tested. Without this step,
        # ``**File:** `/path` `` keeps its asterisks/backticks, the
        # backtick blocks the path detector at line 178 from matching
        # the embedded ``/Users/`` segment, and the raw markdown leaks
        # through as the page title.
        for unwrap in _TITLE_MARKDOWN_UNWRAP:
            cleaned = unwrap.sub(r"\1", cleaned).strip()
        for pat in _TITLE_STRIP_PREFIXES:
            cleaned = pat.sub("", cleaned).strip()
        if _line_is_title_candidate(cleaned):
            first_meaningful = cleaned
            break

    # Truncate to reasonable title length
    if len(first_meaningful) > 80:
        first_meaningful = first_meaningful[:77].rsplit(" ", 1)[0] + "..."

    # Kind-specific prefixing for clarity
    prefix_map = {
        "adr": "Decision",
        "lesson": "Lesson",
        "convention": "Convention",
        "spec": "Spec",
    }
    prefix = prefix_map.get(kind, "")

    # If we have entities, use them for a more specific title
    if entities and len(entities) >= 2:
        entity_title = " + ".join(entities[:2])
        if prefix:
            return f"{prefix}: {entity_title}"
        return entity_title

    if not first_meaningful:
        return ""

    if prefix and not first_meaningful.lower().startswith(prefix.lower()):
        return f"{prefix}: {first_meaningful}"

    return first_meaningful


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower())
    return slug.strip("-")[:80]
