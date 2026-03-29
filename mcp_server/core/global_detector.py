"""Detect whether a memory should be marked as global (cross-project).

Global memories are visible to all projects during recall. They represent
knowledge that transcends any single codebase: architecture rules, coding
conventions, infrastructure facts, security policies, team agreements,
and reusable patterns.

Classification uses weighted keyword/phrase signals across 6 categories.
A memory is global when its score exceeds a threshold AND it doesn't
contain project-specific anchors (file paths, branch names, PR numbers).

Pure business logic -- no I/O.
"""

from __future__ import annotations

import re

# ── Signal categories ───────────────────────────────────────────────────
# Each category contributes to the global score. Phrases (multi-word)
# score higher than single keywords to reduce false positives.

GLOBAL_SIGNALS: dict[str, list[tuple[str, float]]] = {
    "architecture": [
        ("clean architecture", 2.0),
        ("single responsibility", 2.0),
        ("dependency injection", 2.0),
        ("dependency inversion", 2.0),
        ("separation of concerns", 2.0),
        ("composition root", 1.8),
        ("hexagonal architecture", 1.8),
        ("domain driven design", 1.5),
        ("solid principles", 1.8),
        ("design pattern", 1.5),
        ("anti-pattern", 1.5),
        ("coupling", 1.0),
        ("cohesion", 1.0),
        ("abstraction", 0.8),
        ("interface segregation", 1.8),
        ("open closed principle", 1.8),
        ("liskov substitution", 1.8),
    ],
    "convention": [
        ("coding standard", 2.0),
        ("naming convention", 2.0),
        ("code style", 1.5),
        ("best practice", 1.5),
        ("always use", 1.5),
        ("never use", 1.5),
        ("prefer", 0.8),
        ("convention", 1.0),
        ("rule of thumb", 1.5),
        ("we always", 1.5),
        ("we never", 1.5),
        ("team agreement", 2.0),
        ("standard approach", 1.5),
    ],
    "infrastructure": [
        ("server at", 1.8),
        ("database url", 2.0),
        ("connection string", 2.0),
        ("production server", 2.0),
        ("staging server", 2.0),
        ("home network", 1.8),
        ("docker compose", 1.5),
        ("ci/cd pipeline", 1.8),
        ("github actions", 1.5),
        ("deployment", 1.0),
        ("kubernetes", 1.0),
        ("load balancer", 1.5),
        ("reverse proxy", 1.5),
        ("dns", 0.8),
        ("vpn", 1.0),
        ("ssl certificate", 1.5),
        ("backups", 0.8),
        ("backup", 0.8),
        ("monitoring", 0.8),
        ("database", 0.6),
    ],
    "security": [
        ("api key rotation", 2.0),
        ("secret rotation", 2.0),
        ("security policy", 2.0),
        ("access control", 1.5),
        ("authentication", 1.0),
        ("authorization", 1.0),
        ("jwt", 1.0),
        ("oauth", 1.0),
        ("encryption", 1.0),
        ("password policy", 2.0),
        ("credentials", 1.0),
        ("credential", 1.0),
        ("vulnerability", 1.0),
        ("owasp", 1.5),
        ("cors policy", 1.5),
        ("rate limiting", 1.5),
    ],
    "cross_project": [
        ("across all projects", 2.5),
        ("all projects", 2.0),
        ("cross-project", 2.5),
        ("shared across", 2.0),
        ("every project", 2.0),
        ("universal", 1.5),
        ("global rule", 2.5),
        ("global policy", 2.5),
        ("applies everywhere", 2.0),
        ("company-wide", 2.0),
        ("team-wide", 2.0),
        ("organization", 1.0),
        ("reusable", 1.0),
    ],
    "knowledge": [
        ("utc timestamp", 1.8),
        ("wal mode", 1.5),
        ("connection pool", 1.5),
        ("idempotent", 1.5),
        ("eventual consistency", 1.5),
        ("cap theorem", 1.5),
        ("acid", 1.0),
        ("race condition", 1.2),
        ("deadlock", 1.2),
        ("memory leak", 1.2),
        ("cache invalidation", 1.5),
        ("index on", 1.2),
        ("foreign key", 1.0),
        ("migration", 0.8),
        ("schema design", 1.5),
    ],
}

# ── Negative signals — project-specific anchors ─────────────────────────
# Content with these patterns is likely project-specific, not global.

_PROJECT_ANCHORS = re.compile(
    r"(?:"
    r"(?:\.{0,2}/)?(?:[\w@.-]+/){2,}[\w@.-]+\.\w+"  # file paths
    r"|PR\s*#\d+"  # pull request refs
    r"|issue\s*#\d+"  # issue refs
    r"|branch\s+[\w/-]+"  # branch names
    r"|commit\s+[0-9a-f]{7,}"  # commit hashes
    r"|\bv\d+\.\d+\.\d+"  # version numbers
    r")",
    re.IGNORECASE,
)

# Tool log prefix — auto-captured tool output is never global
_TOOL_LOG_PREFIX = re.compile(r"^#\s*Tool:\s", re.MULTILINE)

# IP addresses and hostnames are infrastructure (positive, not negative)
_IP_PATTERN = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
_HOST_PATTERN = re.compile(
    r"\b[\w-]+\.(internal|local|dev|prod|staging)\b",
    re.IGNORECASE,
)

# ── Threshold ───────────────────────────────────────────────────────────

GLOBAL_THRESHOLD = 3.0


# ── Pre-compiled patterns ──────────────────────────────────────────────

_COMPILED_SIGNALS: list[tuple[str, float, re.Pattern[str] | None]] = []

for _cat, _signals in GLOBAL_SIGNALS.items():
    for _phrase, _weight in _signals:
        if " " in _phrase:
            _COMPILED_SIGNALS.append((_phrase, _weight, None))
        else:
            _COMPILED_SIGNALS.append(
                (_phrase, _weight, re.compile(rf"\b{_phrase}\b", re.IGNORECASE))
            )


# ── Public API ──────────────────────────────────────────────────────────


def detect_global(
    content: str,
    tags: list[str] | None = None,
) -> tuple[bool, float, str]:
    """Classify whether memory content should be global.

    Returns:
        (is_global, score, reason)
        - is_global: True if score >= GLOBAL_THRESHOLD
        - score: weighted sum of matched signals
        - reason: best-matching category or "not_global"
    """
    if not content:
        return False, 0.0, "empty"

    # Skip auto-captured tool logs
    if _TOOL_LOG_PREFIX.search(content):
        return False, 0.0, "tool_log"

    lower = content.lower()
    tag_text = " ".join(tags or []).lower()
    haystack = lower + " " + tag_text

    # Score positive signals
    score = 0.0
    category_scores: dict[str, float] = {}

    for phrase, weight, regex in _COMPILED_SIGNALS:
        if regex is not None:
            if regex.search(haystack):
                score += weight
                cat = _category_for_phrase(phrase)
                category_scores[cat] = category_scores.get(cat, 0) + weight
        else:
            if phrase in haystack:
                score += weight
                cat = _category_for_phrase(phrase)
                category_scores[cat] = category_scores.get(cat, 0) + weight

    # Boost for infrastructure indicators
    if _IP_PATTERN.search(content):
        score += 1.0
        category_scores["infrastructure"] = (
            category_scores.get("infrastructure", 0) + 1.0
        )
    if _HOST_PATTERN.search(content):
        score += 1.0
        category_scores["infrastructure"] = (
            category_scores.get("infrastructure", 0) + 1.0
        )

    # Boost for explicit global tags
    global_tags = {"global", "shared", "infrastructure", "cross-project", "universal"}
    tag_overlap = global_tags & {t.lower() for t in (tags or [])}
    if tag_overlap:
        score += 1.5 * len(tag_overlap)
        category_scores["cross_project"] = (
            category_scores.get("cross_project", 0) + 1.5 * len(tag_overlap)
        )

    # Penalize project-specific anchors (but not zero — infra can have paths)
    anchor_count = len(_PROJECT_ANCHORS.findall(content))
    if anchor_count >= 3:
        score *= 0.4
    elif anchor_count >= 1:
        score *= 0.7

    # Determine best category
    if not category_scores:
        return False, 0.0, "not_global"

    best_cat = max(category_scores, key=category_scores.get)  # type: ignore[arg-type]
    is_global = score >= GLOBAL_THRESHOLD
    reason = f"global_{best_cat}" if is_global else "not_global"

    return is_global, round(score, 2), reason


def _category_for_phrase(phrase: str) -> str:
    """Look up which category a phrase belongs to."""
    for cat, signals in GLOBAL_SIGNALS.items():
        for p, _ in signals:
            if p == phrase:
                return cat
    return "unknown"
