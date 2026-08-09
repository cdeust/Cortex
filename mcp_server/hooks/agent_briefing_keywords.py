"""Task-prompt keyword extraction for the agent_briefing hook's FTS query.

Split out of ``agent_briefing.py`` (issue #401 — that file exceeded the
project's 300-line cap, CLAUDE.md § Code Style) to isolate pure text
processing (no I/O, no dependency on the rest of the hook) from prompt
parsing/event control flow and the PG query.
"""

from __future__ import annotations

# source: "words longer than 3 chars" per _extract_task_keywords docstring
_MIN_KEYWORD_CHARS = 3

_STOPWORDS = {
    "the",
    "and",
    "for",
    "that",
    "this",
    "with",
    "from",
    "your",
    "have",
    "will",
    "been",
    "they",
    "what",
    "when",
    "where",
    "which",
    "there",
    "their",
    "about",
    "would",
    "could",
    "should",
    "into",
    "more",
    "some",
    "than",
    "them",
    "then",
    "these",
    "those",
    "each",
    "make",
    "like",
    "just",
    "over",
    "such",
    "take",
    "also",
    "back",
    "after",
    "only",
    "come",
    "made",
    "find",
    "here",
    "thing",
    "many",
    "well",
    "work",
    "need",
    "using",
    "used",
    "code",
    "file",
    "please",
    "ensure",
}


def _extract_task_keywords(prompt: str) -> list[str]:
    """Extract key terms from the agent prompt for FTS query.

    Takes the first 500 chars of the prompt and extracts words
    longer than 3 chars, excluding common stop words.
    """
    words = prompt[:500].lower().split()
    keywords = [
        w.strip(".,;:!?\"'()[]{}")
        for w in words
        if len(w) > _MIN_KEYWORD_CHARS
        and w.lower().strip(".,;:!?\"'()[]{}") not in _STOPWORDS
    ]
    # Return unique keywords, max 8
    seen = set()
    unique = []
    for k in keywords:
        if k not in seen and k:
            seen.add(k)
            unique.append(k)
    return unique[:8]
