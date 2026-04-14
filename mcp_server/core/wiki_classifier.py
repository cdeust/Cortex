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
    "<command-message>",
    "<command-name>",
    "# <command-message>",
    "# <command-name>",
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
    # Leading `#+\s*` tolerates markdown heading prefix before the keyword
    re.compile(r"^#*\s*Implement the following plan", re.IGNORECASE),
    re.compile(r"^#*\s*Execute the following", re.IGNORECASE),
    re.compile(r"^#*\s*You must respond with only", re.IGNORECASE),
    re.compile(r"^#*\s*Perform all verification", re.IGNORECASE),
    re.compile(r"^#*\s*Take the code and split", re.IGNORECASE),
    re.compile(r"^\s*\{[\s\S]*\}\s*$"),  # Pure JSON object
    re.compile(r"^\s*\[[\s\S]*\]\s*$"),  # Pure JSON array
    # Slash-command invocations — only Claude Code UI framing, no knowledge content
    re.compile(r"<command-(message|name|args)>", re.IGNORECASE),
    # Benchmark spell content (Hogwarts benchmark artifacts)
    re.compile(r"^#*\s*Spell:\s*\w+", re.IGNORECASE),
    # Test content shape markers
    re.compile(r"^#*\s*Shape test content", re.IGNORECASE),
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

# ── Hard-negative gate (Eco + Ahrens): disqualifying patterns ─────────
#
# Each of these, if present, is a hard DISQUALIFICATION — single hit blocks
# admission regardless of positive signals. Catches session chat, imperatives,
# narration, status updates, and temporal deixis that should live in session
# logs, not a wiki.

# Imperative verbs in title/first line (task-shaped, not knowledge-shaped)
_IMPERATIVE_TITLE_PATTERNS = [
    re.compile(
        r"^\s*#*\s*(let'?s|lets)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*#*\s*("
        r"use|fetch|take|give|look at|verify|audit|check|make|do|run|"
        r"push|remove|rename|adapt|implement|execute|perform|replace|"
        r"add|delete|update|modify|fix|install|setup|configure|"
        r"create|build|write|test|sync|import|export|move|copy|ensure|"
        r"try|go|start|stop|open|close|clean|restart|refactor|migrate|"
        r"enable|disable|apply|reset|rebuild|regenerate|analyze"
        r")\b",
        re.IGNORECASE,
    ),
    # Second-person imperative directed at the AI
    re.compile(r"^\s*#*\s*you (must|should|need|will|can)\b", re.IGNORECASE),
    # Questions-as-titles (without resolution body)
    re.compile(r"^\s*#*\s*(how|what|why|when|where|can|should|is|does)\b[^.]*\?\s*$"),
]

# First-person narration ("we pushed", "I tried", "we did")
_FIRST_PERSON_PATTERNS = [
    re.compile(
        r"^\s*#*\s*(we|i)\s+"
        r"(pushed|pulled|did|have|did|tried|ran|found|saw|noticed|got|made|"
        r"created|added|removed|fixed|broke|updated|changed|deleted|merged|"
        r"re?-?started|tested|benchmarked|think|need|want|should|re)",
        re.IGNORECASE,
    ),
]

# Status / progress register — NOT knowledge, but work-log entries
_STATUS_PATTERNS = [
    re.compile(
        r"^\s*#*\s*("
        r"successfully|done|failing|failed|broken|working|not working|"
        r"finished|completed|in progress|wip|todo|pending"
        r")\b",
        re.IGNORECASE,
    ),
    # Command/tool output framing
    re.compile(r"local[-_]command[-_](stdout|stderr|stdin|output)", re.IGNORECASE),
    # Test harness metadata
    re.compile(r"session[-_]test[-_]session", re.IGNORECASE),
    re.compile(r"in domain unknown", re.IGNORECASE),
]

# Temporal deixis — "now", "just", "previous", "earlier" make the note
# uninterpretable outside the session in which it was written
_DEIXIS_PATTERNS = [
    re.compile(
        r"^\s*#*\s*("
        r"just now|just did|previous|earlier|last session|new wip|"
        r"the one we|like (we|i) (said|did)|yesterday|today|tomorrow|"
        r"a while ago|recent(ly)?"
        r")\b",
        re.IGNORECASE,
    ),
]


def _fails_hard_negatives(content: str, first_line: str) -> bool:
    """Return True if content hits any hard-negative pattern.

    Hard negatives are single-strike disqualifiers. Any one match blocks
    wiki admission. Patterns check first_line primarily (title shape),
    a few check full content.
    """
    for pat in _IMPERATIVE_TITLE_PATTERNS:
        if pat.search(first_line):
            return True
    for pat in _FIRST_PERSON_PATTERNS:
        if pat.search(first_line):
            return True
    for pat in _STATUS_PATTERNS:
        if pat.search(first_line):
            return True
        if pat.search(content[:500]):  # status framing often appears in first 500 chars
            return True
    for pat in _DEIXIS_PATTERNS:
        if pat.search(first_line):
            return True
    return False


# ── Positive quality signals (admit only if ≥ threshold) ──────────────

_STRUCTURE_HEADING = re.compile(r"^#{1,4}\s+\S", re.MULTILINE)
_STRUCTURE_LIST = re.compile(r"^\s*[-*+]\s+\S", re.MULTILINE)
_STRUCTURE_CODE = re.compile(r"```\w*\n", re.MULTILINE)
_CITATION = re.compile(
    r"\b("
    r"ADR-?\d+|paper|arxiv|doi:|https?://|"
    r"\b[A-Z][a-z]+ (et al\.|&) \d{4}|"
    r"\b[A-Z][a-z]+ \d{4}\b"
    r")",
)
_DECLARATIVE = re.compile(
    r"\b(is|are|means|causes?|because|implies|requires?|enables?|prevents?|"
    r"produces?|results? in|leads? to|defined? as|consists of)\b",
    re.IGNORECASE,
)
_FILE_OR_ENTITY_REF = re.compile(
    r"\b[a-zA-Z_]\w*\.(py|js|ts|md|json|yaml|sql|go|rs|rb|java)\b|"
    r"\b[a-z_]+\(\)|"
    r"\bclass\s+[A-Z]\w+|"
    r"\bdef\s+[a-z_]\w+"
)


def _positive_score(content: str, tags: set[str]) -> int:
    """Count how many positive quality signals the content exhibits.

    Signals (8 total):
      1. Multiple structural elements (heading/list/code)
      2. Contains declarative claim-shaped sentences
      3. Cites paper, ADR, URL, or function/file reference
      4. Minimum substantive length (≥ 200 chars)
      5. Has curated/knowledge tag
      6. Is atomic (not too long, not too short) — 200-3000 chars
      7. Domain vocabulary density — at least 3 distinct technical tokens
      8. References files or code entities
    """
    score = 0
    length = len(content)

    # 1. Structure
    struct = 0
    struct += 1 if _STRUCTURE_HEADING.search(content) else 0
    struct += 1 if _STRUCTURE_LIST.search(content) else 0
    struct += 1 if _STRUCTURE_CODE.search(content) else 0
    if struct >= 1:
        score += 1

    # 2. Declarative claims
    if len(_DECLARATIVE.findall(content)) >= 2:
        score += 1

    # 3. Citations / references
    if _CITATION.search(content):
        score += 1

    # 4. Substantive length
    if length >= 200:
        score += 1

    # 5. Knowledge tag
    _KNOWLEDGE_TAGS = {
        "decision",
        "adr",
        "architecture",
        "spec",
        "design",
        "lesson",
        "convention",
        "rule",
        "standard",
        "paper",
        "research",
        "reference",
    }
    if tags & _KNOWLEDGE_TAGS:
        score += 1

    # 6. Atomic scope (200–3000 chars is the Zettelkasten sweet spot)
    if 200 <= length <= 3000:
        score += 1

    # 7. Domain vocabulary density — at least 3 distinct CamelCase/snake_case
    #    technical tokens
    tech_tokens = set(
        re.findall(r"\b(?:[A-Z][a-z]+[A-Z]\w*|[a-z]+_[a-z_]+)\b", content)
    )
    if len(tech_tokens) >= 3:
        score += 1

    # 8. File/entity references
    if _FILE_OR_ENTITY_REF.search(content):
        score += 1

    return score


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


_POSITIVE_SCORE_THRESHOLD = 4  # must satisfy ≥ 4 of 8 positive signals


def classify_memory(content: str, tags: list[str] | None = None) -> str | None:
    """Classify memory content for wiki sync.

    Inversion (Eco + Ahrens research): default to REJECT. A memory is
    promoted to the wiki only if it passes three gates:

      1. Noise rejection (tool output, JSON, slash-command framing)
      2. Hard-negative gate (imperatives, first-person narration, status,
         temporal deixis — any hit disqualifies)
      3. Positive scoring (≥ 4 of 8 quality signals)

    Explicit knowledge-shaped tags (decision/adr/spec/design/lesson/
    convention/rule) bypass the positive scorer — those are opt-in by
    the caller and presumed wiki-worthy.

    Returns page kind ('adr', 'lesson', 'convention', 'spec', 'note')
    or None if the content should be rejected.
    """
    if not content or len(content.strip()) < 50:
        return None

    stripped = content.strip()
    first_line = stripped.split("\n", 1)[0].strip()

    # Gate 1 — Noise rejection (obvious tool/system/slash artefacts)
    for prefix in _REJECT_PREFIXES:
        if stripped.startswith(prefix):
            return None

    for pattern in _REJECT_PATTERNS:
        if pattern.match(stripped):
            return None

    slug = _slugify(first_line)
    if slug in _REJECT_TITLES:
        return None

    # Gate 2 — Hard-negative gate (task-shape, narration, status, deixis)
    if _fails_hard_negatives(content, first_line):
        return None

    # Tag-based fast-path: explicit knowledge tags bypass positive scoring.
    # The caller has declared intent; trust the declaration.
    tag_set = {t.lower() for t in (tags or [])}
    _EXPLICIT_KNOWLEDGE_TAGS = {
        "decision",
        "adr",
        "architecture",
        "spec",
        "design",
        "lesson",
        "convention",
        "rule",
        "standard",
        "paper",
        "research",
    }
    has_explicit_tag = bool(tag_set & _EXPLICIT_KNOWLEDGE_TAGS)

    # Gate 3 — Positive scoring (only when no explicit knowledge tag)
    if not has_explicit_tag:
        if _positive_score(content, tag_set) < _POSITIVE_SCORE_THRESHOLD:
            return None

    # ─── Admitted — now route to the right kind ──────────────────────

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
