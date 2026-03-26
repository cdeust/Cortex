"""Complementary Learning Systems -- episodic/semantic classification and consolidation.

Based on McClelland et al. (1995) and Go-CLS (Sun et al., Nature Neuroscience 2023):
  - Fast episodic store: captures specific events verbatim
  - Slow semantic store: abstracts recurring patterns into general knowledge

Pure business logic -- no I/O.
"""

from __future__ import annotations

import re


# -- Classification -----------------------------------------------------------

_SEMANTIC_TAGS = frozenset(
    {
        "rule",
        "convention",
        "preference",
        "standard",
        "architecture",
        "principle",
        "pattern",
        "guideline",
        "policy",
        "best-practice",
    }
)

_DECISION_RE = re.compile(
    r"\b(always|never|prefer|standard|must|should|convention|rule)\b",
    re.IGNORECASE,
)
_INSTRUCTION_RE = re.compile(
    r"\b(from now on|going forward|remember to|please always|"
    r"i want you to|make sure to|do not ever|whenever you|"
    r"every time you|respond in|use only|stick to)\b",
    re.IGNORECASE,
)
_ARCHITECTURE_RE = re.compile(
    r"\b(pattern|design|principle|paradigm|architecture|layer|module)\b",
    re.IGNORECASE,
)
_SPECIFIC_RE = re.compile(
    r"(line \d+|\.py:\d+|\.js:\d+|\.ts:\d+|traceback|0x[0-9a-f]+|"
    r"/Users/|/home/|/tmp/|\.log\b|\d{4}-\d{2}-\d{2}T\d{2}:\d{2})",
    re.IGNORECASE,
)


def classify_memory(
    content: str,
    tags: list[str] | None = None,
    directory: str = "",
) -> str:
    """Classify content as 'episodic' or 'semantic'.

    Resolution order:
      1. Tag-based: semantic tags -> "semantic"
      2. Specificity override: line numbers, paths, tracebacks -> "episodic"
      3. Content keywords: decision/architecture words -> "semantic"
      4. Default: "episodic"
    """
    tag_set = {t.lower() for t in (tags or [])}

    if tag_set & _SEMANTIC_TAGS:
        return "semantic"

    has_specific = bool(_SPECIFIC_RE.search(content))
    if has_specific:
        return "episodic"

    has_decision = bool(_DECISION_RE.search(content))
    has_architecture = bool(_ARCHITECTURE_RE.search(content))
    has_instruction = bool(_INSTRUCTION_RE.search(content))
    if has_decision or has_architecture or has_instruction:
        return "semantic"

    return "episodic"


# -- Auto Weight --------------------------------------------------------------


def auto_weight(query: str) -> tuple[float, float]:
    """Determine episodic vs semantic weighting from query text.

    Returns (episodic_weight, semantic_weight).
    """
    has_specific = bool(_SPECIFIC_RE.search(query))
    has_semantic = bool(_DECISION_RE.search(query)) or bool(
        _ARCHITECTURE_RE.search(query)
    )

    if has_specific:
        return 2.0, 1.0
    elif has_semantic:
        return 1.0, 2.0
    else:
        return 1.0, 1.0
