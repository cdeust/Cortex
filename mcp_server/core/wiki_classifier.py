"""Wiki content classifier — determines page kind or rejects noise.

Pure business logic — no I/O. The sync path calls this to decide
whether a memory should become a wiki page, and what kind.

Classification hierarchy (Alexander P2 + Eco):
  1. REJECT: tool invocations, system prompts, JSON, generic instructions
  2. ADR: contains a decision with rationale
  3. LESSON: describes a mistake and its resolution
  4. CONVENTION: establishes a rule or standard
  5. SPEC: describes a feature or system design
  6. NOTE: catch-all for meaningful content
"""

from __future__ import annotations

import re

# ── Rejection patterns ────────────────────────────────────────────────

_REJECT_PREFIXES = (
    "# Tool:",
    "Tool:",
    "tool:",
    "# tool:",
    "System:",
    "system:",
    "<tool_result>",
    "<result>",
)

_REJECT_TITLES = {
    "tool-edit",
    "tool-bash",
    "tool-read",
    "tool-write",
    "tool-grep",
    "tool-glob",
    "tool-search",
}

_REJECT_PATTERNS = [
    re.compile(r"^Implement the following plan", re.IGNORECASE),
    re.compile(r"^Execute the following", re.IGNORECASE),
    re.compile(r"^You must respond with only", re.IGNORECASE),
    re.compile(r"^\s*\{[\s\S]*\}\s*$"),  # Pure JSON object
    re.compile(r"^\s*\[[\s\S]*\]\s*$"),  # Pure JSON array
]

# ── Classification patterns ───────────────────────────────────────────

_ADR_PATTERNS = [
    re.compile(
        r"\b(decided to|decision:|the decision is|chose .+ because|rejected .+ (due to|because)|we will use|selected .+ over)\b",
        re.IGNORECASE,
    ),
]

_LESSON_PATTERNS = [
    re.compile(
        r"\b(the bug was|root cause|lesson learned|mistake was|never again|fix:|fixed by|the issue was|the problem was|turned out)\b",
        re.IGNORECASE,
    ),
]

_CONVENTION_PATTERNS = [
    re.compile(
        r"\b(always use|never |the canonical|convention:|rule:|standard:|must follow|naming convention|coding standard)\b",
        re.IGNORECASE,
    ),
]

_SPEC_TAGS = {"spec", "design", "specification", "feature"}

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


def classify_memory(content: str, tags: list[str] | None = None) -> str | None:
    """Classify memory content for wiki sync.

    Returns page kind ('adr', 'lesson', 'convention', 'spec', 'note')
    or None if the content should be rejected.
    """
    if not content or len(content.strip()) < 50:
        return None

    stripped = content.strip()
    first_line = stripped.split("\n", 1)[0].strip()

    # Rejection gate
    for prefix in _REJECT_PREFIXES:
        if stripped.startswith(prefix):
            return None

    for pattern in _REJECT_PATTERNS:
        if pattern.match(stripped):
            return None

    # Reject if title would be a tool name
    slug = _slugify(first_line)
    if slug in _REJECT_TITLES:
        return None

    # Classification by content patterns (most specific first)
    tag_set = {t.lower() for t in (tags or [])}

    for pat in _ADR_PATTERNS:
        if pat.search(content):
            return "adr"

    if tag_set & {"decision", "adr"}:
        return "adr"

    for pat in _LESSON_PATTERNS:
        if pat.search(content):
            return "lesson"

    if tag_set & {"lesson", "debugging", "fix", "bug-fix"}:
        return "lesson"

    for pat in _CONVENTION_PATTERNS:
        if pat.search(content):
            return "convention"

    if tag_set & {"convention", "rule", "standard"}:
        return "convention"

    if tag_set & _SPEC_TAGS and len(content) > 200:
        return "spec"

    if tag_set & {"architecture", "design"} and len(content) > 200:
        return "spec"

    # Catch-all: meaningful content that passed the gate
    return "note"


def derive_title(
    content: str,
    kind: str,
    tags: list[str] | None = None,
    entities: list[str] | None = None,
) -> str:
    """Derive a meaningful title for a wiki page.

    Strategy (Alexander P4 + Eco):
    1. Strip known prefixes
    2. Use kind-specific extraction
    3. Fall back to entity-based or tag-based title
    4. Last resort: first meaningful sentence
    """
    # Get clean first line
    lines = content.strip().split("\n")
    first_meaningful = ""
    for line in lines:
        cleaned = line.strip()
        for pat in _TITLE_STRIP_PREFIXES:
            cleaned = pat.sub("", cleaned).strip()
        if (
            len(cleaned) > 10
            and not cleaned.startswith("{")
            and not cleaned.startswith("[")
        ):
            first_meaningful = cleaned
            break

    if not first_meaningful:
        first_meaningful = content.strip()[:80]

    # Truncate to reasonable title length
    if len(first_meaningful) > 80:
        # Cut at word boundary
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

    if prefix and not first_meaningful.lower().startswith(prefix.lower()):
        return f"{prefix}: {first_meaningful}"

    return first_meaningful


def _slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower())
    return slug.strip("-")[:80]
