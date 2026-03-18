"""Detect coverage gaps in cognitive domain profiles.

Three blind spot types:
  - Category: work categories appearing in <5% of sessions
  - Tool: tools relevant to domain categories but rarely used
  - Pattern: missing exploration, deep-work, or quick-iteration sessions
"""

from __future__ import annotations

import re
from typing import Any

from mcp_server.core.blindspot_patterns import (
    check_duration_gaps,
    check_exploration_gap,
    count_duration_buckets,
)
from mcp_server.shared.categorizer import CATEGORY_RULES, categorize_with_scores

ALL_CATEGORIES = list(CATEGORY_RULES.keys())

COMMON_TOOLS = [
    "Read",
    "Edit",
    "Write",
    "Grep",
    "Glob",
    "Bash",
    "Agent",
    "WebSearch",
    "WebFetch",
]

TOOL_CATEGORY_RELEVANCE: dict[str, list[str]] = {
    "Read": ["bug-fix", "research", "debug", "refactor", "docs"],
    "Edit": ["bug-fix", "feature", "refactor", "config"],
    "Write": ["feature", "docs", "config"],
    "Grep": ["bug-fix", "debug", "refactor", "research"],
    "Glob": ["refactor", "architecture", "config"],
    "Bash": ["testing", "deployment", "debug", "config"],
    "Agent": ["research", "architecture"],
    "WebSearch": ["research", "architecture"],
    "WebFetch": ["research", "docs"],
}

_TEST_RE = re.compile(
    r"\b(test|spec|assert|expect|xct|xctest|jest|pytest|mocha)\b",
    re.IGNORECASE,
)


def _get_tools_used(conv: dict) -> list[str]:
    raw = conv.get("toolsUsed") or conv.get("tools") or conv.get("toolCalls") or []
    return [
        (t if isinstance(t, str) else (t or {}).get("name", ""))
        for t in raw
        if (t if isinstance(t, str) else (t or {}).get("name", ""))
    ]


def _get_categories(conv: dict) -> set[str]:
    cats = conv.get("categories")
    if isinstance(cats, list) and len(cats) > 0:
        return set(cats)

    text = conv.get("allText") or conv.get("firstMessage") or ""
    if text:
        scores = categorize_with_scores(text)
        result = set(scores.keys())

        tools = _get_tools_used(conv)
        if "Bash" in tools and _TEST_RE.search(text.lower()):
            result.add("testing")

        if result:
            return result

    category = conv.get("category")
    if isinstance(category, str) and category:
        return {category}
    return set()


def _get_top_domain_categories(
    domain_conversations: list[dict], top_n: int = 3
) -> list[str]:
    counts: dict[str, int] = {}
    for conv in domain_conversations:
        for cat in _get_categories(conv):
            counts[cat] = counts.get(cat, 0) + 1
    return [
        cat
        for cat, _ in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:top_n]
    ]


def _global_exploration_ratio(all_conversations: list[dict]) -> float:
    if not all_conversations:
        return 0.0
    exploration_categories = {"research", "architecture"}
    count = 0
    for conv in all_conversations:
        cats = _get_categories(conv)
        if cats & exploration_categories:
            count += 1
    return count / len(all_conversations)


# ---------------------------------------------------------------------------
# Detection functions
# ---------------------------------------------------------------------------


def _detect_category_blind_spots(
    domain_conversations: list[dict],
) -> list[dict[str, Any]]:
    blind_spots: list[dict[str, Any]] = []
    total = len(domain_conversations)
    if total == 0:
        return blind_spots

    for category in ALL_CATEGORIES:
        sessions_with = sum(
            1 for conv in domain_conversations if category in _get_categories(conv)
        )
        ratio = sessions_with / total
        if ratio < 0.05:
            blind_spots.append(
                {
                    "type": "category",
                    "value": category,
                    "severity": "high" if ratio < 0.01 else "medium",
                    "description": f'Category "{category}" appears in only {ratio * 100:.1f}% of sessions (threshold: 5%).',
                    "suggestion": f"Consider intentionally including {category} work in this domain to broaden coverage.",
                }
            )
    return blind_spots


def _detect_tool_blind_spots(
    domain_conversations: list[dict], top_domain_categories: list[str]
) -> list[dict[str, Any]]:
    blind_spots: list[dict[str, Any]] = []
    total = len(domain_conversations)
    if total == 0:
        return blind_spots

    top_cat_set = set(top_domain_categories)

    for tool in COMMON_TOOLS:
        sessions_using = sum(
            1 for conv in domain_conversations if tool in _get_tools_used(conv)
        )
        ratio = sessions_using / total
        if ratio >= 0.05:
            continue

        relevant_categories = TOOL_CATEGORY_RELEVANCE.get(tool, [])
        is_relevant = any(cat in top_cat_set for cat in relevant_categories)
        if not is_relevant:
            continue

        overlap = [cat for cat in relevant_categories if cat in top_cat_set]
        severity = "high" if len(overlap) >= 2 or ratio < 0.01 else "medium"

        blind_spots.append(
            {
                "type": "tool",
                "value": tool,
                "severity": severity,
                "description": f'Tool "{tool}" used in only {ratio * 100:.1f}% of sessions, yet is relevant to domain categories: {", ".join(overlap)}.',
                "suggestion": f'Incorporate "{tool}" more regularly in {"/".join(top_domain_categories)} tasks to leverage its full potential.',
            }
        )
    return blind_spots


def _detect_pattern_blind_spots(
    domain_conversations: list[dict], all_conversations: list[dict]
) -> list[dict[str, Any]]:
    total = len(domain_conversations)
    if total == 0:
        return []

    exploration_categories = {"research", "architecture"}
    domain_exploration_count = sum(
        1
        for conv in domain_conversations
        if _get_categories(conv) & exploration_categories
    )
    global_exp_ratio = _global_exploration_ratio(all_conversations)

    blind_spots = check_exploration_gap(
        domain_exploration_count / total, global_exp_ratio
    )

    domain_short, domain_long = count_duration_buckets(domain_conversations)
    global_short, global_long = count_duration_buckets(all_conversations)
    global_total = len(all_conversations) or 1

    blind_spots += check_duration_gaps(
        total,
        domain_short,
        domain_long,
        global_short / global_total,
        global_long / global_total,
    )

    return blind_spots


# ---------------------------------------------------------------------------
# Main export
# ---------------------------------------------------------------------------


def detect_blind_spots(
    domain_id: str,
    domain_conversations: list[dict],
    all_conversations: list[dict],
    profiles: dict | None = None,
) -> list[dict[str, Any]]:
    """Detect blind spots for a single domain."""
    top_categories = _get_top_domain_categories(domain_conversations)

    category_bs = _detect_category_blind_spots(domain_conversations)
    tool_bs = _detect_tool_blind_spots(domain_conversations, top_categories)
    pattern_bs = _detect_pattern_blind_spots(domain_conversations, all_conversations)

    return category_bs + tool_bs + pattern_bs
