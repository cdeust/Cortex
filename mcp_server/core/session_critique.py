"""Session self-critique — structured reflection for metacognitive improvement.

Generates structured critique of session activity by analyzing:
  - Tool usage patterns (diversity, over-reliance, gaps)
  - Decision quality signals (reversals, contradictions)
  - Coverage assessment (what was explored vs what was missed)
  - Actionable improvement suggestions

This module produces the *structure* and *analysis* for self-critique.
No LLM calls — operates on session data and memory statistics.

Pure business logic — no I/O.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.session_critique_format import (
    analyze_decisions,
    compute_overall_score,
    format_critique_text,
)

# ── Tool Usage Analysis ───────────────────────────────────────────────────

EXPECTED_TOOL_DISTRIBUTION = {
    "Read": 0.25,
    "Edit": 0.15,
    "Write": 0.10,
    "Grep": 0.10,
    "Glob": 0.05,
    "Bash": 0.15,
    "Agent": 0.05,
    "WebSearch": 0.05,
    "WebFetch": 0.05,
}


def _count_tools(tools_used: list[str]) -> dict[str, int]:
    """Count occurrences of each tool."""
    counts: dict[str, int] = {}
    for tool in tools_used:
        counts[tool] = counts.get(tool, 0) + 1
    return counts


def _tool_usage_suggestions(
    diversity: float,
    over_reliance: list[str],
    under_used: list[str],
) -> list[str]:
    """Generate actionable suggestions from tool usage metrics."""
    suggestions: list[str] = []
    if over_reliance:
        suggestions.append(
            f"Heavy reliance on {', '.join(over_reliance)} — "
            "consider diversifying tool usage"
        )
    if len(under_used) > 3:
        suggestions.append(
            f"Unused tools: {', '.join(under_used[:3])} — these might have been useful"
        )
    if diversity < 0.3:
        suggestions.append("Very low tool diversity — explore more tools")
    return suggestions


def analyze_tool_usage(
    tools_used: list[str],
    session_type: str = "general",
) -> dict[str, Any]:
    """Analyze tool usage diversity and balance.

    Returns:
      - diversity_score: 0-1 (higher = more diverse)
      - over_reliance: list of tools used disproportionately
      - under_used: list of potentially useful but unused tools
      - suggestions: actionable improvement notes
    """
    if not tools_used:
        return {
            "diversity_score": 0.0,
            "over_reliance": [],
            "under_used": list(EXPECTED_TOOL_DISTRIBUTION.keys()),
            "suggestions": ["No tools were used in this session"],
        }

    total = len(tools_used)
    counts = _count_tools(tools_used)

    diversity = min(1.0, len(counts) / max(1, len(EXPECTED_TOOL_DISTRIBUTION) * 0.6))
    over_reliance = [t for t, c in counts.items() if c / total > 0.5 and total > 5]
    under_used = [t for t in EXPECTED_TOOL_DISTRIBUTION if t not in counts]
    suggestions = _tool_usage_suggestions(diversity, over_reliance, under_used)

    return {
        "diversity_score": round(diversity, 3),
        "over_reliance": over_reliance,
        "under_used": under_used,
        "suggestions": suggestions,
        "tool_counts": counts,
    }


# ── Coverage Analysis ─────────────────────────────────────────────────────


def _compute_breadth_depth(files_touched: list[str]) -> tuple[float, float]:
    """Compute breadth (directory diversity) and depth (repeat visits) scores."""
    if not files_touched:
        return 0.0, 0.0

    unique_dirs = {f.rsplit("/", 1)[0] for f in files_touched if "/" in f}
    breadth = min(1.0, len(unique_dirs) / 5)

    file_counts: dict[str, int] = {}
    for f in files_touched:
        file_counts[f] = file_counts.get(f, 0) + 1
    depth = min(1.0, max(file_counts.values()) / 5)

    return breadth, depth


def _coverage_suggestions(
    breadth: float,
    depth: float,
    entity_coverage: float,
    total_entities: int,
    files_touched_count: int,
) -> list[str]:
    """Generate suggestions from coverage metrics."""
    suggestions: list[str] = []
    if breadth < 0.2 and files_touched_count > 3:
        suggestions.append("Narrow focus — consider exploring adjacent files/modules")
    if depth > 0.8 and breadth < 0.3:
        suggestions.append("Deep but narrow — might be missing the bigger picture")
    if entity_coverage < 0.1 and total_entities > 10:
        suggestions.append(
            "Low entity coverage — many known entities weren't referenced"
        )
    return suggestions


def analyze_coverage(
    files_touched: list[str],
    entities_mentioned: list[str],
    total_entities: int = 0,
    total_domain_files: int = 0,
) -> dict[str, Any]:
    """Analyze how thoroughly the session explored the problem space.

    Returns:
      - file_coverage: fraction of domain files touched
      - entity_coverage: fraction of known entities referenced
      - breadth_score: 0-1 (higher = broader exploration)
      - depth_score: 0-1 (higher = deeper focus)
      - suggestions: improvement notes
    """
    file_coverage = (
        len(set(files_touched)) / max(1, total_domain_files)
        if total_domain_files > 0
        else 0.0
    )
    entity_coverage = (
        len(set(entities_mentioned)) / max(1, total_entities)
        if total_entities > 0
        else 0.0
    )
    breadth, depth = _compute_breadth_depth(files_touched)

    return {
        "file_coverage": round(min(1.0, file_coverage), 3),
        "entity_coverage": round(min(1.0, entity_coverage), 3),
        "breadth_score": round(breadth, 3),
        "depth_score": round(depth, 3),
        "suggestions": _coverage_suggestions(
            breadth,
            depth,
            entity_coverage,
            total_entities,
            len(files_touched),
        ),
    }


# ── Full Session Critique ─────────────────────────────────────────────────


def _collect_top_suggestions(
    tool_analysis: dict[str, Any],
    decision_analysis: dict[str, Any],
    coverage_analysis: dict[str, Any],
    limit: int = 5,
) -> list[str]:
    """Gather and prioritize suggestions from all analysis sections."""
    all_suggestions = (
        tool_analysis["suggestions"]
        + decision_analysis["suggestions"]
        + coverage_analysis["suggestions"]
    )
    return all_suggestions[:limit]


def generate_critique(
    tools_used: list[str],
    memories: list[dict[str, Any]],
    files_touched: list[str] | None = None,
    entities_mentioned: list[str] | None = None,
    total_entities: int = 0,
    duration_minutes: float = 0,
    turn_count: int = 0,
) -> dict[str, Any]:
    """Generate a full structured session critique."""
    tool_analysis = analyze_tool_usage(tools_used)
    decision_analysis = analyze_decisions(memories)
    coverage_analysis = analyze_coverage(
        files_touched or [],
        entities_mentioned or [],
        total_entities=total_entities,
    )

    overall = compute_overall_score(tool_analysis, decision_analysis, coverage_analysis)
    top_suggestions = _collect_top_suggestions(
        tool_analysis,
        decision_analysis,
        coverage_analysis,
    )

    return {
        "tool_analysis": tool_analysis,
        "decision_analysis": decision_analysis,
        "coverage_analysis": coverage_analysis,
        "overall_score": round(overall, 3),
        "top_suggestions": top_suggestions,
        "critique_text": format_critique_text(
            overall,
            tool_analysis,
            decision_analysis,
            coverage_analysis,
            top_suggestions,
            duration_minutes,
            turn_count,
        ),
    }
