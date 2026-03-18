"""Work-category classification for cognitive sessions.

Pattern-matching against 10 categories. Single words score 1.0, multi-word
phrases score 1.5. categorize() returns the best match; categorize_with_scores()
returns all non-zero scores.
"""

from __future__ import annotations

import re

CATEGORY_RULES: dict[str, list[str]] = {
    "bug-fix": [
        "fix",
        "bug",
        "broken",
        "crash",
        "error",
        "issue",
        "regression",
        "failing",
    ],
    "feature": ["add", "implement", "new", "build", "create", "introduce", "support"],
    "refactor": [
        "refactor",
        "restructure",
        "clean up",
        "simplify",
        "extract",
        "rename",
    ],
    "research": [
        "research",
        "investigate",
        "explore",
        "evaluate",
        "compare",
        "analyze",
    ],
    "config": ["config", "setup", "install", "environment", "settings", "dependency"],
    "docs": ["document", "readme", "changelog", "comment", "guide", "tutorial"],
    "debug": ["debug", "log", "trace", "inspect", "diagnose", "why is"],
    "architecture": [
        "architecture",
        "design",
        "pattern",
        "system",
        "module",
        "protocol",
    ],
    "deployment": [
        "deploy",
        "ci/cd",
        "pipeline",
        "release",
        "docker",
        "publish",
        "production",
    ],
    "testing": ["test", "spec", "assert", "mock", "coverage", "unit test"],
}

# Pre-compile word-boundary regexes for single-word signals
_SIGNAL_PATTERNS: dict[str, list[tuple[str, float, re.Pattern | None]]] = {}
for _cat, _signals in CATEGORY_RULES.items():
    _compiled = []
    for _signal in _signals:
        if " " in _signal:
            _compiled.append((_signal, 1.5, None))
        else:
            _compiled.append(
                (_signal, 1.0, re.compile(rf"\b{_signal}\b", re.IGNORECASE))
            )
    _SIGNAL_PATTERNS[_cat] = _compiled


def categorize_with_scores(text: str | None) -> dict[str, float]:
    """Score text against all categories, returning non-zero scores."""
    if not text:
        return {}
    lower = text.lower()
    scores: dict[str, float] = {}

    for category, patterns in _SIGNAL_PATTERNS.items():
        score = 0.0
        for signal, weight, regex in patterns:
            if regex is not None:
                if regex.search(lower):
                    score += weight
            else:
                if signal in lower:
                    score += weight
        if score > 0:
            scores[category] = score

    return scores


def categorize(text: str | None) -> str:
    """Classify text into a single best work category.

    Returns the highest-scoring category, with tie-breaking favoring
    multi-word phrase matches. Defaults to "general" if no match.
    """
    if not text:
        return "general"

    scores = categorize_with_scores(text)
    if not scores:
        return "general"

    lower = text.lower()
    best = "general"
    best_score = 0.0
    best_phrase_count = 0

    for cat, sc in scores.items():
        phrase_count = sum(
            1
            for signal, _, regex in _SIGNAL_PATTERNS[cat]
            if regex is None and signal in lower
        )
        if sc > best_score + 0.5:
            best_score = sc
            best = cat
            best_phrase_count = phrase_count
        elif sc >= best_score and sc > best_score - 0.5:
            if phrase_count > best_phrase_count or (
                phrase_count == best_phrase_count and sc > best_score
            ):
                best_score = sc
                best = cat
                best_phrase_count = phrase_count

    return best
