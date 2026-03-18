"""Session critique formatting, scoring, and decision analysis helpers.

Companion module to session_critique.py — handles composite score
computation, markdown text formatting, and decision quality analysis.

Pure business logic — no I/O.
"""

from __future__ import annotations

import re
from typing import Any

# ── Decision Analysis ─────────────────────────────────────────────────────

_REVERSAL_RE = re.compile(
    r"\b(actually|instead|changed my mind|wait|no,|scratch that|"
    r"let me redo|on second thought|reverted|rolled back)\b",
    re.IGNORECASE,
)

_DECISION_RE = re.compile(
    r"\b(decided|chose|switched|went with)\b",
    re.IGNORECASE,
)


def _is_decision_memory(m: dict[str, Any]) -> bool:
    """Check if a memory represents a decision."""
    tags = m.get("tags") or []
    has_decision_tag = any(isinstance(t, str) and t.lower() == "decision" for t in tags)
    has_decision_content = bool(_DECISION_RE.search(m.get("content", "")))
    return has_decision_tag or has_decision_content


def _decision_suggestions(
    decision_count: int,
    reversal_count: int,
    avg_confidence: float,
    memory_count: int,
) -> list[str]:
    """Generate suggestions from decision analysis metrics."""
    suggestions: list[str] = []
    if reversal_count > 2:
        suggestions.append(
            f"{reversal_count} reversals detected — consider more upfront analysis"
        )
    if avg_confidence < 0.5:
        suggestions.append(
            "Low average decision confidence — gather more info before deciding"
        )
    if decision_count == 0 and memory_count > 5:
        suggestions.append(
            "No explicit decisions recorded — consider documenting key choices"
        )
    return suggestions


def analyze_decisions(
    memories: list[dict[str, Any]],
    session_memories: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Analyze decision quality from session memories.

    Returns:
      - decision_count: total decisions made
      - reversal_count: decisions that were reversed
      - confidence_avg: average confidence of decisions
      - suggestions: improvement notes
    """
    decisions = [m for m in memories if _is_decision_memory(m)]
    reversals = [
        m
        for m in (session_memories or memories)
        if _REVERSAL_RE.search(m.get("content", ""))
    ]

    confidences = [m.get("confidence", 0.5) for m in decisions]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.5

    return {
        "decision_count": len(decisions),
        "reversal_count": len(reversals),
        "confidence_avg": round(avg_confidence, 3),
        "suggestions": _decision_suggestions(
            len(decisions),
            len(reversals),
            avg_confidence,
            len(memories),
        ),
    }


# ── Scoring & Formatting ─────────────────────────────────────────────────


def compute_overall_score(
    tool_analysis: dict[str, Any],
    decision_analysis: dict[str, Any],
    coverage_analysis: dict[str, Any],
) -> float:
    """Compute composite critique score from sub-analyses."""
    reversal_ratio = min(
        1.0,
        decision_analysis["reversal_count"]
        / max(1, decision_analysis["decision_count"]),
    )
    scores = [
        tool_analysis["diversity_score"],
        1.0 - reversal_ratio,
        decision_analysis["confidence_avg"],
        coverage_analysis["breadth_score"],
    ]
    return sum(scores) / len(scores)


def format_critique_text(
    overall: float,
    tool_analysis: dict[str, Any],
    decision_analysis: dict[str, Any],
    coverage_analysis: dict[str, Any],
    top_suggestions: list[str],
    duration_minutes: float,
    turn_count: int,
) -> str:
    """Format the critique as a markdown summary."""
    lines = ["## Session Self-Critique", ""]

    if duration_minutes > 0:
        lines.append(f"**Duration**: {duration_minutes:.0f} min, {turn_count} turns")
        lines.append("")

    lines.append(f"**Overall Score**: {overall:.0%}")
    lines.append(f"- Tool diversity: {tool_analysis['diversity_score']:.0%}")
    lines.append(f"- Decision confidence: {decision_analysis['confidence_avg']:.0%}")
    lines.append(f"- Exploration breadth: {coverage_analysis['breadth_score']:.0%}")
    lines.append("")

    if top_suggestions:
        lines.append("**Improvements**:")
        for s in top_suggestions:
            lines.append(f"- {s}")
    else:
        lines.append("*No significant issues detected.*")

    return "\n".join(lines)
