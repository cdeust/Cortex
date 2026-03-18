"""Felder-Silverman cognitive style classification from session behavior.

Multi-dimensional classification:
  - Active/Reflective: tool edit/read ratios + duration + keywords
  - Sensing/Intuitive: concrete vs abstract keywords + file counts
  - Sequential/Global: file access non-linearity + refactor keywords
Plus categorical: problemDecomposition, explorationStyle, verificationBehavior.
"""

from __future__ import annotations

import re
from typing import Any

ABSTRACT_KEYWORDS = [
    "architecture",
    "pattern",
    "system",
    "design",
    "module",
    "abstraction",
    "principle",
    "paradigm",
    "framework",
    "conceptual",
    "high-level",
    "strategy",
    "tradeoff",
    "trade-off",
    "evolve",
    "scalable",
    "decoupled",
    "interface",
]

CONCRETE_KEYWORDS = [
    "example",
    "specifically",
    "instance",
    "step-by-step",
    "file",
    "line",
    "function",
    "variable",
    "output",
    "value",
    "exact",
    "literal",
    "actual",
    "current",
    "particular",
    "record",
    "entry",
]

PLANNING_KEYWORDS = [
    "plan",
    "strategy",
    "before",
    "first",
    "outline",
    "design",
    "consider",
    "think",
    "review",
    "analyse",
    "analyze",
    "evaluate",
    "assess",
]

TRIAL_KEYWORDS = [
    "try",
    "attempt",
    "test",
    "experiment",
    "quick",
    "iterate",
    "tweak",
    "adjust",
    "patch",
    "hack",
    "workaround",
]

_TEST_RE = re.compile(
    r"\b(test|spec|assert|expect|xct|xctest|jest|pytest|mocha|coverage|tdd|unit.?test|integration.?test)\b",
    re.IGNORECASE,
)


def _count_tool(conv: dict, tool_name: str) -> int:
    raw = conv.get("toolsUsed") or conv.get("tools") or conv.get("toolCalls") or []
    return sum(
        1
        for t in raw
        if (t if isinstance(t, str) else (t or {}).get("name", "")) == tool_name
    )


def _total_tool_calls(conv: dict) -> int:
    raw = conv.get("toolsUsed") or conv.get("tools") or conv.get("toolCalls") or []
    return len(raw)


def _count_keywords(text: str | None, keywords: list[str]) -> int:
    if not text:
        return 0
    lower = text.lower()
    return sum(1 for kw in keywords if kw in lower)


def _non_linearity_score(conv: dict) -> float:
    files = conv.get("filesTouched") or conv.get("files") or []
    if not files:
        return 0.0
    dirs = set()
    for f in files:
        parts = str(f).replace("\\", "/").split("/")
        dirs.add("/".join(parts[:-1]) if len(parts) > 1 else ".")
    return len(dirs) / len(files)


def _clamp(v: float) -> float:
    return max(-1.0, min(1.0, v))


def _score_active_reflective(conversations: list[dict]) -> float:
    if not conversations:
        return 0.0
    total_score = 0.0
    counted = 0
    for conv in conversations:
        total = _total_tool_calls(conv)
        dur = conv.get("durationMinutes") or conv.get("duration") or 0
        summary = conv.get("summary") or conv.get("body") or conv.get("title") or ""
        score = 0.0
        signals = 0.0
        if dur > 0:
            if dur < 10:
                score += 1
                signals += 1
            elif dur > 30:
                score -= 1
                signals += 1
        if total > 0:
            edit_count = _count_tool(conv, "Edit") + _count_tool(conv, "Write")
            read_count = _count_tool(conv, "Read") + _count_tool(conv, "Grep")
            if edit_count / total > 0.4:
                score += 1
                signals += 1
            if read_count / total > 0.4:
                score -= 1
                signals += 1
        trial = _count_keywords(summary, TRIAL_KEYWORDS)
        plan = _count_keywords(summary, PLANNING_KEYWORDS)
        if trial > plan:
            score += 0.5
            signals += 0.5
        elif plan > trial:
            score -= 0.5
            signals += 0.5
        if signals > 0:
            total_score += score / signals
            counted += 1
    return _clamp(total_score / counted) if counted > 0 else 0.0


def _score_sensing_intuitive(conversations: list[dict]) -> float:
    if not conversations:
        return 0.0
    total_score = 0.0
    counted = 0
    for conv in conversations:
        summary = conv.get("summary") or conv.get("body") or conv.get("title") or ""
        files = len(conv.get("filesTouched") or conv.get("files") or [])
        score = 0.0
        signals = 0.0
        concrete = _count_keywords(summary, CONCRETE_KEYWORDS)
        abstract = _count_keywords(summary, ABSTRACT_KEYWORDS)
        if concrete > 0 or abstract > 0:
            net = concrete - abstract
            mx = max(concrete, abstract)
            score += net / mx
            signals += 1
        if files > 5:
            score += 0.5
            signals += 0.5
        if signals > 0:
            total_score += score / signals
            counted += 1
    return _clamp(total_score / counted) if counted > 0 else 0.0


def _score_sequential_global(conversations: list[dict]) -> float:
    if not conversations:
        return 0.0
    total_score = 0.0
    counted = 0
    for conv in conversations:
        nl = _non_linearity_score(conv)
        total = _total_tool_calls(conv)
        summary = conv.get("summary") or conv.get("body") or conv.get("title") or ""
        files_list = conv.get("filesTouched") or conv.get("files") or []
        files = len(files_list)
        score = 0.0
        signals = 0.0
        if files > 0:
            score += 1 - 2 * nl
            signals += 1
        refactor_terms = ["refactor", "restructure", "rename", "move", "reorganize"]
        if _count_keywords(summary, refactor_terms) > 0:
            score -= 0.5
            signals += 0.5
        if total > 0 and files > 0:
            cpf = total / files
            if cpf < 2:
                score -= 0.5
                signals += 0.5
            elif cpf > 6:
                score += 0.5
                signals += 0.5
        if signals > 0:
            total_score += score / signals
            counted += 1
    return _clamp(total_score / counted) if counted > 0 else 0.0


def _classify_problem_decomposition(conversations: list[dict]) -> str:
    if not conversations:
        return "top-down"
    top_down = 0
    bottom_up = 0
    for conv in conversations:
        summary = conv.get("summary") or conv.get("body") or conv.get("title") or ""
        plan_hits = _count_keywords(summary, PLANNING_KEYWORDS)
        read_first = (
            _count_tool(conv, "Read")
            + _count_tool(conv, "Grep")
            + _count_tool(conv, "Glob")
        )
        edit_count = _count_tool(conv, "Edit") + _count_tool(conv, "Write")
        if plan_hits > 2 and edit_count > read_first:
            top_down += 1
        elif read_first > edit_count:
            bottom_up += 1
        elif plan_hits > 0:
            top_down += 1
        else:
            bottom_up += 1
    return "top-down" if top_down >= bottom_up else "bottom-up"


def _classify_exploration_style(conversations: list[dict]) -> str:
    if not conversations:
        return "depth-first"
    depth = 0
    breadth = 0
    for conv in conversations:
        total = _total_tool_calls(conv)
        files = len(conv.get("filesTouched") or conv.get("files") or [])
        if files == 0 or total == 0:
            continue
        cpf = total / files
        if cpf > 5:
            depth += 1
        elif cpf < 3:
            breadth += 1
    if depth == breadth:
        return "depth-first"
    return "depth-first" if depth > breadth else "breadth-first"


def _classify_verification_behavior(conversations: list[dict]) -> str:
    if not conversations:
        return "no-test"
    test_first = 0
    test_after = 0
    no_test = 0
    for conv in conversations:
        bash = _count_tool(conv, "Bash")
        reads = _count_tool(conv, "Read") + _count_tool(conv, "Grep")
        edits = _count_tool(conv, "Edit") + _count_tool(conv, "Write")
        text = conv.get("allText") or conv.get("firstMessage") or ""
        has_test = bool(_TEST_RE.search(text))
        if bash == 0 and not has_test:
            no_test += 1
        elif has_test and reads >= edits:
            test_first += 1
        elif has_test or bash > 0:
            test_after += 1
        else:
            no_test += 1
    if no_test >= test_first and no_test >= test_after:
        return "no-test"
    if test_first >= test_after:
        return "test-first"
    return "test-after"


def classify_style(conversations: Any) -> dict[str, Any]:
    """Classify Felder-Silverman cognitive style from conversations."""
    convs = conversations if isinstance(conversations, list) else []
    return {
        "activeReflective": _score_active_reflective(convs),
        "sensingIntuitive": _score_sensing_intuitive(convs),
        "sequentialGlobal": _score_sequential_global(convs),
        "problemDecomposition": _classify_problem_decomposition(convs),
        "explorationStyle": _classify_exploration_style(convs),
        "verificationBehavior": _classify_verification_behavior(convs),
    }
