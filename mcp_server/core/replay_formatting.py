"""Replay formatting — context restoration for post-compaction injection.

Formats checkpoint state and hot memories as injectable markdown
for hippocampal context reconstruction after Claude Code compaction.

Pure business logic — no I/O.
"""

from __future__ import annotations

import json
import re


# ── Micro-checkpoint Detection ───────────────────────────────────────────

_MICRO_ERROR_RE = re.compile(
    r"(error|exception|traceback|failed|crash|bug)\b", re.IGNORECASE
)
_MICRO_DECISION_RE = re.compile(
    r"\b(decided|chose|switched|migrated|will use|going with|opted)\b",
    re.IGNORECASE,
)

_CRITICAL_TAGS = {"critical", "important", "architecture", "breaking"}


def should_micro_checkpoint(
    content: str,
    tags: list[str],
    surprise: float = 0.0,
    tool_call_count: int = 0,
    cooldown: int = 5,
) -> tuple[bool, str]:
    """Check if content warrants a micro-checkpoint.

    Triggers on error detection, decisions, high surprise, or critical tags.
    Returns (should_checkpoint, reason).
    """
    if tool_call_count < cooldown:
        return False, ""

    if _MICRO_ERROR_RE.search(content):
        return True, "error_detected"

    if _MICRO_DECISION_RE.search(content):
        return True, "decision_made"

    if surprise > 0.8:
        return True, "high_surprise_event"

    tag_set = {t.lower() for t in tags}
    if tag_set & _CRITICAL_TAGS:
        return True, "critical_tag"

    return False, ""


# ── JSON Field Parsing ───────────────────────────────────────────────────


def _parse_json_field(value) -> list:
    """Safely parse a JSON field that might be string or list."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return []
    return []


# ── Restoration Formatting ───────────────────────────────────────────────


def format_restoration(
    checkpoint: dict | None,
    anchored_memories: list[dict],
    recent_memories: list[dict],
    hot_memories: list[dict],
    directory: str = "",
) -> str:
    """Format restoration data as injectable markdown for context reconstruction."""
    lines: list[str] = ["# Cortex Context Restoration (Hippocampal Replay)", ""]

    if checkpoint:
        _format_checkpoint(lines, checkpoint)
    if anchored_memories:
        _format_anchored(lines, anchored_memories)
    if recent_memories:
        _format_recent(lines, recent_memories)
    if hot_memories:
        _format_hot(lines, hot_memories)
    if directory:
        lines.append(f"*Restored for directory: {directory}*")

    return "\n".join(lines)


def _format_checkpoint(lines: list[str], checkpoint: dict) -> None:
    """Append checkpoint section to restoration lines."""
    lines.append("## What You Were Doing")

    task = checkpoint.get("current_task", "")
    if task:
        lines.append(f"**Task:** {task}")

    files = _parse_json_field(checkpoint.get("files_being_edited"))
    if files:
        lines.append(f"**Files:** {', '.join(str(f) for f in files)}")

    _append_list_field(lines, checkpoint, "key_decisions", "Decisions")
    _append_list_field(lines, checkpoint, "open_questions", "Open questions")
    _append_list_field(lines, checkpoint, "next_steps", "Next steps")
    _append_list_field(lines, checkpoint, "active_errors", "Active errors")

    custom = checkpoint.get("custom_context", "")
    if custom:
        lines.append(f"\n{custom}")
    lines.append("")


def _append_list_field(
    lines: list[str],
    checkpoint: dict,
    field_name: str,
    label: str,
) -> None:
    """Append a bulleted list section if the field has items."""
    items = _parse_json_field(checkpoint.get(field_name))
    if items:
        lines.append(f"**{label}:**")
        for item in items:
            lines.append(f"- {item}")


def _format_anchored(lines: list[str], memories: list[dict]) -> None:
    """Append anchored memories section."""
    lines.append("## Critical Facts (Anchored)")
    for m in memories:
        content = _truncate(m.get("content", ""), 300)
        lines.append(f"- {content}")
    lines.append("")


def _format_recent(lines: list[str], memories: list[dict]) -> None:
    """Append recent working memory section."""
    lines.append("## Working Memory (Recently Stored)")
    for m in memories[:6]:
        content = _truncate(m.get("content", ""), 250)
        created = str(m.get("created_at", ""))[:16]
        lines.append(f"- [{created}] {content}")
    lines.append("")


def _format_hot(lines: list[str], memories: list[dict]) -> None:
    """Append hot project context section."""
    lines.append("## Active Project Context")
    for m in memories[:6]:
        content = _truncate(m.get("content", ""), 200)
        heat = m.get("heat", 0)
        lines.append(f"- [{heat:.2f}] {content}")
    lines.append("")


def _truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis if it exceeds max_len."""
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text
