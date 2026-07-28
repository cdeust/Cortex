"""Wiki classifier pattern tables — pure data, no logic.

Extracted from ``wiki_classifier.py`` (issue #134, file exceeded the
500-line hard limit in coding-standards.md §4). This module holds every
regex/constant table the admission gates and legacy-kind router consult:
rejection patterns, legacy-kind detection patterns, hard-negative gate
patterns, the audit-tag denylist, and the positive-quality-signal
patterns. No behavior lives here — see ``wiki_classifier_gates.py`` for
the functions that consume these tables.
"""

from __future__ import annotations

import re

# ── Rejection patterns ────────────────────────────────────────────────

REJECT_PREFIXES = (
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

REJECT_TITLES = {
    "tool-edit",
    "tool-bash",
    "tool-read",
    "tool-write",
    "tool-grep",
    "tool-glob",
    "tool-search",
}

REJECT_PATTERNS = [
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

ADR_PATTERNS = [
    re.compile(
        r"\b(decided to|decision:|the decision is|"
        r"chose .+ because|rejected .+ (due to|because)|"
        r"we will use|selected .+ over)\b",
        re.IGNORECASE,
    ),
]

LESSON_PATTERNS = [
    re.compile(
        r"\b(the bug was|root cause|lesson learned|mistake was|"
        r"never again|fix:|fixed by|"
        r"the issue was|the problem was|turned out)\b",
        re.IGNORECASE,
    ),
]

CONVENTION_PATTERNS = [
    re.compile(
        r"\b(always use|never |the canonical|convention:|rule:|standard:|"
        r"must follow|naming convention|coding standard)\b",
        re.IGNORECASE,
    ),
]

SPEC_TAGS = {"spec", "design", "specification", "feature"}

# ── Hard-negative gate (Eco + Ahrens): disqualifying patterns ─────────
#
# Each of these, if present, is a hard DISQUALIFICATION — single hit blocks
# admission regardless of positive signals. Catches session chat, imperatives,
# narration, status updates, and temporal deixis that should live in session
# logs, not a wiki.

# Imperative verbs in title/first line (task-shaped, not knowledge-shaped)
IMPERATIVE_TITLE_PATTERNS = [
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
FIRST_PERSON_PATTERNS = [
    re.compile(
        r"^\s*#*\s*(we|i)\s+"
        r"(pushed|pulled|did|have|did|tried|ran|found|saw|noticed|got|made|"
        r"created|added|removed|fixed|broke|updated|changed|deleted|merged|"
        r"re?-?started|tested|benchmarked|think|need|want|should|re)",
        re.IGNORECASE,
    ),
]

# Status / progress register — NOT knowledge, but work-log entries
STATUS_PATTERNS = [
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
DEIXIS_PATTERNS = [
    re.compile(
        r"^\s*#*\s*("
        r"just now|just did|previous|earlier|last session|new wip|"
        r"the one we|like (we|i) (said|did)|yesterday|today|tomorrow|"
        r"a while ago|recent(ly)?"
        r")\b",
        re.IGNORECASE,
    ),
]

# Path- or URL-shaped titles — these are file/URL access audit records,
# not curated knowledge. Keep them as memories (for recall), refuse
# promotion to the wiki.
PATH_OR_URL_TITLE_PATTERNS = [
    # Absolute POSIX / Windows path as title
    re.compile(r"^\s*#*\s*[/~]"),
    re.compile(r"^\s*#*\s*[A-Za-z]:[\\/]"),  # Windows drive letter
    # URL as title
    re.compile(r"^\s*#*\s*(https?|ftp|file|ssh|git)://", re.IGNORECASE),
    # Lone filename as the bulk of the title
    re.compile(
        r"^\s*#*\s*[\w.-]+\.(pdf|png|jpg|jpeg|svg|gif|zip|tar\.gz|docx?|xlsx?|csv|log|yaml|yml)\b",
        re.IGNORECASE,
    ),
    # Path embedded mid-line ("also on /Users/...", "fix the file at C:\\..."):
    # any absolute POSIX path or Windows drive path anywhere in the title.
    # Bug found 2026-05-12: pages like
    # specs/2026-04-17-also-on-users-cdeust-documents-developments-...md
    # passed the start-of-line check, then slugify stripped the leading "/"
    # and folded the entire path into the slug.
    re.compile(r"(?:^|\s)/(Users|home|root|opt|var|etc|tmp)/", re.IGNORECASE),
    re.compile(r"(?:^|\s)[A-Za-z]:[\\/]"),
]

# YAML-frontmatter / key:value lines that leaked through as titles when the
# real title was missing. Reject lines that are purely "key: value" where
# the value is a timestamp, identifier, or boolean — they're metadata,
# not titles.  Bug found 2026-05-12: 10 ADRs slugged as
# "decision-created-2026-04-15t09-29-10z" because the YAML "created:"
# line was the first non-{}/[] line in the body.
YAML_KV_TITLE_PATTERNS = [
    # `created: 2026-04-15T09:29:10Z`, `updated: 2026-04-15`, `date: ...`
    re.compile(
        r"^\s*(created|updated|date|timestamp|time|id|uuid|version)\s*:\s*\S",
        re.IGNORECASE,
    ),
    # Bare ISO-8601 timestamp anywhere (would slug to t09-29-10z form)
    re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}[:-]\d{2}[:-]\d{2}", re.IGNORECASE),
]

# Session / audit artefact tags — these are recall-fodder, not wiki-worthy.
# Any hit in tags auto-rejects from the wiki (memory is preserved separately).
#
# 2026-05-17 (user feedback "that's the same for all kind of category"):
# PostToolUse auto-captures are journal entries — tool dumps, command
# outputs, edit diffs — useful as memories for halo retrieval but
# pollute the wiki with hundreds of ``Lesson: Command: `git log...```
# pages that aren't curated knowledge. Adding ``auto-captured`` and
# ``tool:bash``/``tool:edit`` etc. as audit tags so they stay in PG
# memory but never become wiki pages. Real wiki pages come from
# explicit ``remember`` calls with curated content.
AUDIT_TAGS = frozenset(
    {
        "_backfill",
        "imported",
        "session-summary",
        "tool-output",
        "auto-captured",
        "tool:bash",
        "tool:edit",
        "tool:write",
        "tool:multiedit",
        "tool:notebookedit",
        "tool:read",
        "tool:notebookread",
        "tool:glob",
        "tool:grep",
        "tool:webfetch",
        "tool:websearch",
        # 2026-05-17 (user feedback "wiki is still far from being curated
        # documentation"): codebase_analyze dumped one wiki page per scanned
        # file PER scan invocation — 2176 of 2248 notes were the same
        # auth/middleware/crypto files repeated 290-349 times each.
        # ``seeded`` is the tag set by seed_project; ``codebase`` is the
        # tag set by codebase_analyze's file-level extractor. Both belong
        # in PG memory (recall substrate, halo retrieval) but never on a
        # wiki page meant for curated knowledge.
        "seeded",
        "codebase",
        "code-review",
        "stage-1",
        "stage-2",
        "stage-3",
        "stage-4",
        "stage-5",
        "stage-6",
        "stage-7",
        "stage-8",
        "stage-9",
        "stage-10",
        "stage-11",
        "audit",
        "automated",
        "wip",
        "progress",
    }
)

# Audit/review-shaped title patterns — "stage N:", "code review", "audit:",
# "session N" — these are work-product reports, not durable knowledge.
AUDIT_TITLE_PATTERNS = [
    re.compile(r"\bstage[ -]?\d+\b", re.IGNORECASE),
    re.compile(
        r"\b(code[ -]?review|audit[ -]?report|review[ -]?notes?)\b", re.IGNORECASE
    ),
    re.compile(r"\bsession[ -]?(summary|log|report|\d+)\b", re.IGNORECASE),
]

# ── Positive quality signals (admit only if ≥ threshold) ──────────────

STRUCTURE_HEADING = re.compile(r"^#{1,4}\s+\S", re.MULTILINE)
STRUCTURE_LIST = re.compile(r"^\s*[-*+]\s+\S", re.MULTILINE)
STRUCTURE_CODE = re.compile(r"```\w*\n", re.MULTILINE)
CITATION = re.compile(
    r"\b("
    r"ADR-?\d+|paper|arxiv|doi:|https?://|"
    r"\b[A-Z][a-z]+ (et al\.|&) \d{4}|"
    r"\b[A-Z][a-z]+ \d{4}\b"
    r")",
)
DECLARATIVE = re.compile(
    r"\b(is|are|means|causes?|because|implies|requires?|enables?|prevents?|"
    r"produces?|results? in|leads? to|defined? as|consists of)\b",
    re.IGNORECASE,
)
FILE_OR_ENTITY_REF = re.compile(
    r"\b[a-zA-Z_]\w*\.(py|js|ts|md|json|yaml|sql|go|rs|rb|java)\b|"
    r"\b[a-z_]+\(\)|"
    r"\bclass\s+[A-Z]\w+|"
    r"\bdef\s+[a-z_]\w+"
)

# Knowledge tags used both by the positive-signal scoring (signal 5) and by
# the explicit-tag fast path in the legacy-kind router.
KNOWLEDGE_TAGS = {
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

# Unsourced engineering default (calibration pending): must satisfy ≥ 4 of 8
# positive signals. Not paper-sourced; revisit if classifier precision drifts.
POSITIVE_SCORE_THRESHOLD = 4
