"""Activation extraction for behavioral feature dictionary.

Extracts 27D activation vectors from conversation records.
Dimensions: tool ratios (7), keyword densities (4), temporal signals (5),
derived (1), category scores (10).

Pure business logic -- no I/O.
"""

from __future__ import annotations

from mcp_server.shared.linear_algebra import zeros
from mcp_server.core.style_classifier import (
    ABSTRACT_KEYWORDS,
    CONCRETE_KEYWORDS,
    PLANNING_KEYWORDS,
    TRIAL_KEYWORDS,
)

# ---------------------------------------------------------------------------
# Signal names -- ordered dimensions of the activation space
# ---------------------------------------------------------------------------

TOOL_SIGNALS = [
    "tool:Read",
    "tool:Edit",
    "tool:Write",
    "tool:Grep",
    "tool:Glob",
    "tool:Bash",
    "tool:Agent",
]
KEYWORD_SIGNALS = ["kw:abstract", "kw:concrete", "kw:planning", "kw:trial"]
TEMPORAL_SIGNALS = [
    "tmp:duration",
    "tmp:turnCount",
    "tmp:burst",
    "tmp:exploration",
    "tmp:fileSpread",
]
DERIVED_SIGNALS = ["drv:editReadRatio"]
CATEGORY_NAMES = [
    "cat:bug-fix",
    "cat:feature",
    "cat:refactoring",
    "cat:testing",
    "cat:documentation",
    "cat:devops",
    "cat:code-review",
    "cat:debugging",
    "cat:architecture",
    "cat:general",
]

SIGNAL_NAMES = (
    TOOL_SIGNALS + KEYWORD_SIGNALS + TEMPORAL_SIGNALS + DERIVED_SIGNALS + CATEGORY_NAMES
)
D = len(SIGNAL_NAMES)  # 27

# ---------------------------------------------------------------------------
# Category keyword map for scoring
# ---------------------------------------------------------------------------

_CATEGORY_KEYWORDS = {
    "bug-fix": ["fix", "bug", "error", "issue", "crash", "broken"],
    "feature": ["add", "implement", "create", "new", "feature"],
    "refactoring": ["refactor", "clean", "restructure", "rename", "move"],
    "testing": ["test", "spec", "coverage", "assert", "expect"],
    "documentation": ["doc", "readme", "comment", "explain"],
    "devops": ["deploy", "ci", "docker", "build", "pipeline"],
    "code-review": ["review", "check", "audit", "inspect"],
    "debugging": ["debug", "trace", "log", "inspect", "breakpoint"],
    "architecture": ["architecture", "design", "pattern", "module", "layer"],
    "general": [],
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _count_keyword_density(text: str | None, keywords: list[str]) -> float:
    """Count density of keyword hits in text."""
    if not text:
        return 0.0
    lower = text.lower()
    words = len(lower.split()) or 1
    hits = sum(1 for kw in keywords if kw in lower)
    return hits / words


def _count_tool(tools: list, name: str) -> int:
    """Count occurrences of a named tool in a tool usage list."""
    return sum(
        1
        for t in tools
        if (t if isinstance(t, str) else (t or {}).get("name", "")) == name
    )


def _extract_tool_ratios(activation: list[float], tools: list) -> None:
    """Fill tool ratio dimensions (indices 0-6)."""
    total = len(tools) or 1
    tool_names = ["Read", "Edit", "Write", "Grep", "Glob", "Bash", "Agent"]
    for i, tn in enumerate(tool_names):
        activation[i] = _count_tool(tools, tn) / total


def _extract_keyword_densities(
    activation: list[float],
    text: str | None,
) -> None:
    """Fill keyword density dimensions (indices 7-10)."""
    activation[7] = _count_keyword_density(text, ABSTRACT_KEYWORDS)
    activation[8] = _count_keyword_density(text, CONCRETE_KEYWORDS)
    activation[9] = _count_keyword_density(text, PLANNING_KEYWORDS)
    activation[10] = _count_keyword_density(text, TRIAL_KEYWORDS)


def _extract_temporal_signals(
    activation: list[float],
    conv: dict,
    tools: list,
) -> None:
    """Fill temporal signal dimensions (indices 11-15)."""
    duration = conv.get("duration") or 0
    activation[11] = min(duration / 3600000, 1)
    activation[12] = min((conv.get("turnCount") or 0) / 50, 1)
    activation[13] = 1 if (duration > 0 and duration < 600000) else 0
    activation[14] = 1 if (conv.get("turnCount") or 0) > 20 else 0

    total = len(tools) or 1
    glob_count = _count_tool(tools, "Glob")
    read_count = _count_tool(tools, "Read")
    activation[15] = min((glob_count + read_count) / total, 1)


def _extract_derived_ratio(activation: list[float], tools: list) -> None:
    """Fill derived edit/read ratio dimension (index 16)."""
    edit_count = _count_tool(tools, "Edit") + _count_tool(tools, "Write")
    read_grep = _count_tool(tools, "Read") + _count_tool(tools, "Grep")
    activation[16] = (
        edit_count / read_grep if read_grep > 0 else (1 if edit_count > 0 else 0)
    )


def _extract_category_scores(activation: list[float], text: str) -> None:
    """Fill category score dimensions (indices 17-26)."""
    lower_text = text.lower()
    any_cat = False
    for i, kws in enumerate(_CATEGORY_KEYWORDS.values()):
        if not kws:
            continue
        score = sum(1 for kw in kws if kw in lower_text)
        activation[17 + i] = min(score / len(kws), 1)
        if score > 0:
            any_cat = True
    if not any_cat:
        activation[26] = 0.5


# ---------------------------------------------------------------------------
# Main extraction function
# ---------------------------------------------------------------------------


def extract_session_activation(conversation: dict) -> list[float]:
    """Extract a 27D activation vector from a conversation record."""
    activation = zeros(D)
    tools = conversation.get("toolsUsed") or []
    text = conversation.get("allText") or conversation.get("firstMessage") or ""

    _extract_tool_ratios(activation, tools)
    _extract_keyword_densities(activation, text)
    _extract_temporal_signals(activation, conversation, tools)
    _extract_derived_ratio(activation, tools)
    _extract_category_scores(activation, text or "")

    return activation
