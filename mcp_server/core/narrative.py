"""Narrative engine — project story generation from memory.

Generates prose summaries of project activity from memory records:
  - Decision extraction: keyword + tag matching
  - Event extraction: high-importance memories + event keywords
  - Entity aggregation: top entities by frequency
  - Topic discovery: high-heat focus areas

Pure business logic — no I/O. Receives memory data, returns narratives.
"""

from __future__ import annotations

import re
from typing import Any

# ── Keyword Sets ──────────────────────────────────────────────────────────

_DECISION_KEYWORDS = frozenset(
    {
        "decided",
        "chose",
        "choosing",
        "switched",
        "migrated",
        "replaced",
        "using",
        "adopted",
        "selected",
        "picked",
        "went with",
    }
)

_EVENT_KEYWORDS = frozenset(
    {
        "error",
        "fix",
        "fixed",
        "bug",
        "resolved",
        "broke",
        "crash",
        "deployed",
        "released",
        "implemented",
        "completed",
        "refactored",
    }
)

_DECISION_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _DECISION_KEYWORDS) + r")\b",
    re.IGNORECASE,
)
_EVENT_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _EVENT_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


# ── Extraction Functions ──────────────────────────────────────────────────


def extract_decisions(memories: list[dict[str, Any]]) -> list[str]:
    """Extract decision statements from memories.

    A memory is a decision if:
      - Content matches decision keywords, OR
      - Tags include "decision"
    """
    decisions: list[str] = []
    for mem in memories:
        content = mem.get("content", "")
        tags = mem.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]

        is_decision = "decision" in [t.lower() for t in tags] or bool(
            _DECISION_RE.search(content)
        )
        if is_decision:
            # Truncate to first 150 chars for readability
            text = content[:150].strip()
            if len(content) > 150:
                text += "..."
            decisions.append(text)

    return decisions


def extract_events(
    memories: list[dict[str, Any]],
    importance_threshold: float = 0.7,
) -> list[str]:
    """Extract significant events from memories.

    An event is either:
      - High importance (above threshold), OR
      - Content matches event keywords
    """
    events: list[str] = []
    for mem in memories:
        content = mem.get("content", "")
        importance = mem.get("importance", 0.5)

        is_event = importance >= importance_threshold or bool(_EVENT_RE.search(content))
        if is_event:
            text = content[:150].strip()
            if len(content) > 150:
                text += "..."
            events.append(text)

    return events


def extract_top_entities(
    memories: list[dict[str, Any]],
    max_entities: int = 10,
) -> list[str]:
    """Extract most frequently mentioned entities across memories.

    Uses simple word-frequency heuristic on CamelCase and file paths.
    """
    entity_counts: dict[str, int] = {}

    camel_re = re.compile(r"\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b")
    path_re = re.compile(r"[\w./]+\.\w{1,4}\b")

    for mem in memories:
        content = mem.get("content", "")
        for match in camel_re.findall(content):
            entity_counts[match] = entity_counts.get(match, 0) + 1
        for match in path_re.findall(content):
            if "/" in match or "." in match:
                entity_counts[match] = entity_counts.get(match, 0) + 1

    sorted_entities = sorted(entity_counts.items(), key=lambda x: x[1], reverse=True)
    return [name for name, _ in sorted_entities[:max_entities]]


def extract_hot_topics(
    memories: list[dict[str, Any]],
    heat_threshold: float = 0.7,
    max_topics: int = 5,
) -> list[str]:
    """Extract current focus areas from high-heat memories."""
    hot = [m for m in memories if m.get("heat", 0) >= heat_threshold]
    hot.sort(key=lambda m: m.get("heat", 0), reverse=True)

    topics: list[str] = []
    for mem in hot[:max_topics]:
        content = mem.get("content", "")[:100].strip()
        if content:
            topics.append(content)
    return topics


# ── Narrative Assembly ────────────────────────────────────────────────────


def _assemble_narrative_text(
    memory_count: int,
    decisions: list[str],
    events: list[str],
    entities: list[str],
    topics: list[str],
    directory: str,
    period_label: str,
) -> str:
    """Assemble formatted narrative prose from extracted components."""
    lines: list[str] = []
    header = "# Project Narrative"
    if directory:
        header += f" — {directory}"
    if period_label:
        header += f" ({period_label})"
    lines.append(header)
    lines.append("")

    lines.append(f"Based on {memory_count} memories.")
    lines.append("")

    _append_section(lines, "## Key Decisions", decisions[:10])
    _append_section(lines, "## Significant Events", events[:10])

    if entities:
        lines.append("## Key Entities")
        lines.append(", ".join(entities))
        lines.append("")

    _append_section(lines, "## Current Focus", topics)

    if not decisions and not events and not topics:
        lines.append("*No significant activity recorded in this period.*")

    return "\n".join(lines)


def _append_section(lines: list[str], heading: str, items: list[str]) -> None:
    """Append a bulleted section to lines if items exist."""
    if not items:
        return
    lines.append(heading)
    for item in items:
        lines.append(f"- {item}")
    lines.append("")


def generate_narrative(
    memories: list[dict[str, Any]],
    directory: str = "",
    period_label: str = "",
) -> dict[str, Any]:
    """Generate a project narrative from a set of memories.

    Returns:
      - narrative: formatted prose string
      - decisions: list of decision strings
      - events: list of event strings
      - entities: list of top entity names
      - topics: list of hot topic strings
      - memory_count: total memories analyzed
    """
    decisions = extract_decisions(memories)
    events = extract_events(memories)
    entities = extract_top_entities(memories)
    topics = extract_hot_topics(memories)

    narrative = _assemble_narrative_text(
        len(memories),
        decisions,
        events,
        entities,
        topics,
        directory,
        period_label,
    )

    return {
        "narrative": narrative,
        "decisions": decisions,
        "events": events,
        "entities": entities,
        "topics": topics,
        "memory_count": len(memories),
    }


def generate_brief_summary(
    memories: list[dict[str, Any]],
    max_chars: int = 300,
) -> str:
    """Generate a one-paragraph brief summary for context injection."""
    decisions = extract_decisions(memories)
    events = extract_events(memories)
    topics = extract_hot_topics(memories, max_topics=3)

    parts: list[str] = []
    if topics:
        parts.append(f"Focus: {', '.join(topics[:3])}")
    if decisions:
        parts.append(f"Decisions: {'; '.join(decisions[:2])}")
    if events:
        parts.append(f"Events: {'; '.join(events[:2])}")

    summary = ". ".join(parts)
    if len(summary) > max_chars:
        summary = summary[: max_chars - 3] + "..."
    return summary
