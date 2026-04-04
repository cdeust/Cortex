"""Handler: sync_instructions — push memory insights back into CLAUDE.md.

Reads hot memories for the current project directory, extracts key insights
(decisions, patterns, conventions), and appends or updates a
'## Memory Insights' section in CLAUDE.md.

This closes the loop between Cortex's thermodynamic memory and the Claude
Code instruction file that is loaded at the start of every session.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

# ── Schema ────────────────────────────────────────────────────────────────────

schema = {
    "description": "Sync top memory insights into CLAUDE.md for the project directory. Adds or refreshes a '## Memory Insights' section.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Project directory containing CLAUDE.md (default: cwd)",
            },
            "max_insights": {
                "type": "integer",
                "description": "Maximum number of insight bullets to include (default 10)",
            },
            "min_heat": {
                "type": "number",
                "description": "Minimum memory heat to include (default 0.3)",
            },
            "dry_run": {
                "type": "boolean",
                "description": "Preview the section without writing (default false)",
            },
        },
    },
}

# ── Singleton ─────────────────────────────────────────────────────────────────

_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        settings = get_memory_settings()
        _store = MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)
    return _store


# ── Helpers ───────────────────────────────────────────────────────────────────

_SECTION_START = "<!-- cortex:memory-insights:start -->"
_SECTION_END = "<!-- cortex:memory-insights:end -->"
# Backward compat: also match old cortex markers
_LEGACY_START = "<!-- cortex:memory-insights:start -->"
_LEGACY_END = "<!-- cortex:memory-insights:end -->"

_DECISION_RE = re.compile(
    r"\b(decided|chose|switching|migrated|using|adopted|went with|replaced)\b",
    re.IGNORECASE,
)


def _extract_insights(memories: list[dict[str, Any]], max_insights: int) -> list[str]:
    """Pick the most useful bullets from hot memories."""
    # Prefer decisions, then high-importance, then high-heat
    decisions = [m for m in memories if _DECISION_RE.search(m.get("content", ""))]
    others = [m for m in memories if m not in decisions]

    ordered = sorted(decisions, key=lambda m: m.get("heat", 0), reverse=True)
    ordered += sorted(others, key=lambda m: m.get("importance", 0), reverse=True)

    insights = []
    seen: set[str] = set()
    for mem in ordered[: max_insights * 2]:
        text = mem.get("content", "").strip()
        if not text:
            continue
        # Truncate long memories
        bullet = text[:120].replace("\n", " ")
        if bullet in seen:
            continue
        seen.add(bullet)
        insights.append(bullet)
        if len(insights) >= max_insights:
            break

    return insights


def _build_section(insights: list[str]) -> str:
    lines = [
        _SECTION_START,
        "## Memory Insights",
        "",
        "Auto-synced from Cortex memory. Do not edit manually.",
        "",
    ]
    for bullet in insights:
        lines.append(f"- {bullet}")
    lines += ["", _SECTION_END]
    return "\n".join(lines)


def _update_claude_md(
    claude_md_path: Path, section: str, dry_run: bool
) -> dict[str, Any]:
    """Insert or replace the memory insights section in CLAUDE.md."""
    if not claude_md_path.exists():
        if dry_run:
            return {"action": "would_create", "path": str(claude_md_path)}
        claude_md_path.write_text(section + "\n", encoding="utf-8")
        return {"action": "created", "path": str(claude_md_path)}

    original = claude_md_path.read_text(encoding="utf-8")

    start_idx = original.find(_SECTION_START)
    end_idx = original.find(_SECTION_END)
    end_len = len(_SECTION_END)
    # Backward compat: detect legacy cortex markers
    if start_idx == -1:
        start_idx = original.find(_LEGACY_START)
    if end_idx == -1:
        end_idx = original.find(_LEGACY_END)
        end_len = len(_LEGACY_END)

    if start_idx != -1 and end_idx != -1:
        # Replace existing section (uses new cortex markers)
        before = original[:start_idx]
        after = original[end_idx + end_len :]
        updated = before + section + after
        action = "updated"
    else:
        # Append new section
        updated = original.rstrip() + "\n\n" + section + "\n"
        action = "appended"

    if dry_run:
        return {
            "action": f"would_{action}",
            "path": str(claude_md_path),
            "preview": section,
        }

    claude_md_path.write_text(updated, encoding="utf-8")
    return {"action": action, "path": str(claude_md_path)}


# ── Handler ───────────────────────────────────────────────────────────────────


def _fetch_memories(store: MemoryStore, directory: str, min_heat: float) -> list[dict]:
    """Fetch relevant memories for directory, falling back to hot memories."""
    memories = store.get_memories_for_directory(directory, min_heat=min_heat)
    if not memories:
        memories = store.get_hot_memories(min_heat=min_heat, limit=50)
    return memories


def _find_claude_md(directory: str) -> Path:
    """Find CLAUDE.md in directory or one level up."""
    resolved = Path(directory).resolve()
    claude_md = resolved / "CLAUDE.md"
    if not claude_md.exists():
        parent = resolved.parent / "CLAUDE.md"
        if parent.exists():
            return parent
    return claude_md


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Sync memory insights into CLAUDE.md."""
    args = args or {}
    directory = args.get("directory", "") or os.getcwd()
    max_insights = int(args.get("max_insights", 10))
    min_heat = float(args.get("min_heat", 0.3))
    dry_run = bool(args.get("dry_run", False))

    memories = _fetch_memories(_get_store(), directory, min_heat)
    if not memories:
        return {"synced": False, "reason": "no_memories_found", "directory": directory}

    insights = _extract_insights(memories, max_insights)
    if not insights:
        return {
            "synced": False,
            "reason": "no_insights_extracted",
            "memory_count": len(memories),
        }

    result = _update_claude_md(
        _find_claude_md(directory), _build_section(insights), dry_run
    )
    result.update(
        {
            "synced": True,
            "insights_count": len(insights),
            "memory_count": len(memories),
            "dry_run": dry_run,
        }
    )
    return result
