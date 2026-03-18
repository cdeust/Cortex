"""Memory & query enrichment pipeline.

Two enrichment strategies (no external APIs):
  1. Doc2Query  -- generate synthetic search queries at index time.
  2. Concept expansion -- expand a query with related terms at retrieval time.

Heuristics:
  - ConceptNet-style synonym/hypernym mappings (concept_vocabulary.py)
  - COMET-style pattern templates ("X is used for ...", "X causes ...")
  - Doc2Query: extract question-answerable nouns, generate wh-questions

Pure business logic -- no I/O.
"""

from __future__ import annotations

import re
from collections import Counter

from mcp_server.core.concept_vocabulary import CONCEPT_MAP, REVERSE_MAP

# ── Doc2Query ─────────────────────────────────────────────────────────────

_QUESTION_TEMPLATES = [
    "What is {noun}?",
    "How does {noun} work?",
    "Why was {noun} changed?",
    "What caused the {noun}?",
    "How to fix {noun}?",
    "When was {noun} introduced?",
    "What does {noun} do?",
    "How to use {noun}?",
]

_CODE_TOKEN_RE = re.compile(r"`([^`]+)`|(?:^|\s)([\w._]+(?:\.py|\.js|\.go|\.rs)?)\b")
_ERROR_NAME_RE = re.compile(r"\b(\w+(?:Error|Exception|Warning|Failure))\b")
_DECISION_RE = re.compile(
    r"(?:decided|chose|switched|selected|migrated)\s+(?:to\s+)?(\w+(?:\s+\w+){0,2})",
    re.IGNORECASE,
)
_STOP = {
    "that",
    "this",
    "with",
    "from",
    "they",
    "their",
    "have",
    "will",
    "been",
    "were",
}


def _extract_key_nouns(content: str, max_nouns: int = 8) -> list[str]:
    """Extract the most salient noun phrases from content."""
    candidates: Counter = Counter()
    for m in _CODE_TOKEN_RE.finditer(content):
        token = (m.group(1) or m.group(2) or "").strip()
        if token and len(token) > 2:
            candidates[token] += 3
    for m in _ERROR_NAME_RE.finditer(content):
        candidates[m.group(1)] += 2
    for m in _DECISION_RE.finditer(content):
        candidates[m.group(1).strip()] += 2
    for w in content.split():
        clean = w.strip(".,!?;:()[]{}\"'`-").lower()
        if len(clean) > 4 and clean.isalpha():
            candidates[clean] += 1
    top = [
        (n, c)
        for n, c in candidates.most_common(max_nouns * 2)
        if n.lower() not in _STOP
    ]
    return [n for n, _ in top[:max_nouns]]


def generate_synthetic_queries(content: str, max_queries: int = 5) -> list[str]:
    """Generate synthetic search queries from document content."""
    nouns = _extract_key_nouns(content, max_nouns=6)
    if not nouns:
        return []
    queries: list[str] = []
    for noun in nouns[:max_queries]:
        template = _QUESTION_TEMPLATES[len(queries) % len(_QUESTION_TEMPLATES)]
        queries.append(template.format(noun=noun))
    return queries[:max_queries]


def build_enriched_content(content: str) -> str:
    """Append synthetic queries to content as search augmentation."""
    queries = generate_synthetic_queries(content)
    if not queries:
        return content
    return content + "\n\n<!-- doc2query -->\n" + "\n".join(queries)


# ── Concept expansion ─────────────────────────────────────────────────────


def expand_query(query: str, max_expansions: int = 5) -> list[str]:
    """Expand a query with related terms from the concept vocabulary."""
    words = query.lower().split()
    expansions: Counter = Counter()
    for word in words:
        clean = word.strip(".,!?;:()[]{}\"'`")
        if clean in CONCEPT_MAP:
            for related in CONCEPT_MAP[clean]:
                expansions[related] += 2
        if clean in REVERSE_MAP:
            for related in REVERSE_MAP[clean]:
                expansions[related] += 1
    query_lower = query.lower()
    expansions = Counter(
        {t: c for t, c in expansions.items() if t.lower() not in query_lower}
    )
    return [term for term, _ in expansions.most_common(max_expansions)]


def build_expanded_query(query: str) -> str:
    """Build an expanded query string with related terms appended."""
    expansions = expand_query(query, max_expansions=3)
    if not expansions:
        return query
    return query + " " + " ".join(expansions)


# ── COMET-style commonsense patterns ──────────────────────────────────────

_COMET_TEMPLATES = [
    ("{X} is used to {Y}", "purpose"),
    ("{X} causes {Y}", "causation"),
    ("{X} requires {Y}", "dependency"),
    ("{X} enables {Y}", "enablement"),
]


def generate_comet_frames(subject: str, object_hint: str = "") -> list[str]:
    """Generate COMET-style commonsense inference frames."""
    obj = object_hint or "downstream systems"
    return [t.replace("{X}", subject).replace("{Y}", obj) for t, _ in _COMET_TEMPLATES]
