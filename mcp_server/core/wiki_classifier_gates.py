"""Wiki classifier admission gates — hard-negative and quality scoring.

Extracted from ``wiki_classifier.py`` (issue #134, file exceeded the
500-line hard limit in coding-standards.md §4). These are the pure
functions the legacy-kind router (``wiki_classifier._classify_to_legacy_kind``)
calls to decide whether content is admitted to the wiki, before routing
it to a kind. No I/O, no globals — pattern tables live in
``wiki_classifier_patterns.py``.
"""

from __future__ import annotations

import re

from mcp_server.core.wiki_classifier_patterns import (
    AUDIT_TAGS,
    AUDIT_TITLE_PATTERNS,
    CITATION,
    DECLARATIVE,
    DEIXIS_PATTERNS,
    FILE_OR_ENTITY_REF,
    FIRST_PERSON_PATTERNS,
    IMPERATIVE_TITLE_PATTERNS,
    KNOWLEDGE_TAGS,
    PATH_OR_URL_TITLE_PATTERNS,
    STATUS_PATTERNS,
    STRUCTURE_CODE,
    STRUCTURE_HEADING,
    STRUCTURE_LIST,
)


def fails_hard_negatives(content: str, first_line: str) -> bool:
    """Return True if content hits any hard-negative pattern.

    Hard negatives are single-strike disqualifiers. Any one match blocks
    wiki admission. Patterns check first_line primarily (title shape),
    a few check full content.
    """
    for pat in IMPERATIVE_TITLE_PATTERNS:
        if pat.search(first_line):
            return True
    for pat in FIRST_PERSON_PATTERNS:
        if pat.search(first_line):
            return True
    for pat in STATUS_PATTERNS:
        if pat.search(first_line):
            return True
        if pat.search(content[:500]):  # status framing often appears in first 500 chars
            return True
    for pat in DEIXIS_PATTERNS:
        if pat.search(first_line):
            return True
    for pat in PATH_OR_URL_TITLE_PATTERNS:
        if pat.search(first_line):
            return True
    for pat in AUDIT_TITLE_PATTERNS:
        if pat.search(first_line):
            return True
    return False


def fails_audit_tag_gate(tags: set[str]) -> bool:
    """Return True if any audit/session tag is present.

    Audit-tagged memories are valuable for recall but should never be
    promoted to the wiki — the wiki is for curated specs, ADRs,
    architecture, security, and lessons.
    """
    return bool(tags & AUDIT_TAGS)


# At least this many declarative claims are needed to earn the claims point.
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_MIN_DECLARATIVE_CLAIMS = 2

# Atomic-scope band. source: comment at gate 6 below — the 200–3000 char band
# is an unsourced engineering default for "a self-contained note"
# (calibration pending), NOT a value from Luhmann's Zettelkasten method.
_ATOMIC_SCOPE_MIN_CHARS = 200
_ATOMIC_SCOPE_MAX_CHARS = 3000

# source: comment at gate 7 below — "at least 3 distinct CamelCase/snake_case
# technical tokens".
_MIN_TECH_TOKENS = 3


def positive_score(content: str, tags: set[str]) -> int:
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
    struct += 1 if STRUCTURE_HEADING.search(content) else 0
    struct += 1 if STRUCTURE_LIST.search(content) else 0
    struct += 1 if STRUCTURE_CODE.search(content) else 0
    if struct >= 1:
        score += 1

    # 2. Declarative claims
    if len(DECLARATIVE.findall(content)) >= _MIN_DECLARATIVE_CLAIMS:
        score += 1

    # 3. Citations / references
    if CITATION.search(content):
        score += 1

    # 4. Substantive length
    if length >= _ATOMIC_SCOPE_MIN_CHARS:
        score += 1

    # 5. Knowledge tag
    if tags & KNOWLEDGE_TAGS:
        score += 1

    # 6. Atomic scope. The 200–3000 char band is an unsourced engineering
    #    default for "a self-contained note" (calibration pending), NOT a
    #    value from Luhmann's Zettelkasten method, which sets no char range.
    if _ATOMIC_SCOPE_MIN_CHARS <= length <= _ATOMIC_SCOPE_MAX_CHARS:
        score += 1

    # 7. Domain vocabulary density — at least 3 distinct CamelCase/snake_case
    #    technical tokens
    tech_tokens = set(
        re.findall(r"\b(?:[A-Z][a-z]+[A-Z]\w*|[a-z]+_[a-z_]+)\b", content)
    )
    if len(tech_tokens) >= _MIN_TECH_TOKENS:
        score += 1

    # 8. File/entity references
    if FILE_OR_ENTITY_REF.search(content):
        score += 1

    return score
