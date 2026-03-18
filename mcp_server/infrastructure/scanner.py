"""Data ingestion from ~/.claude/ — discovers memories and conversations.

- Memories: walk projects/[name]/memory/[file].md, parse YAML frontmatter
- Conversations: walk projects/[name]/[session].jsonl, read head+tail
- Head/tail: first 32KB + last 8KB for efficiency on large JSONL files
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp_server.infrastructure.config import CLAUDE_DIR
from mcp_server.infrastructure.file_io import list_dir, read_text_file, stat_file
from mcp_server.infrastructure.scanner_parse import (
    build_conversation_record,
    extract_message_stats,
    extract_metadata_fields,
)
from mcp_server.shared.yaml_parser import parse_yaml_frontmatter

HEAD_BYTES = 32768
TAIL_BYTES = 8192


def _parse_jsonl_lines(lines: list[str]) -> list[dict]:
    """Parse JSONL lines, skipping blanks and invalid JSON."""
    records: list[dict] = []
    for line in lines:
        trimmed = line.strip()
        if not trimmed:
            continue
        try:
            records.append(json.loads(trimmed))
        except (json.JSONDecodeError, ValueError):
            pass
    return records


def read_head_tail(file_path: str | Path) -> list[dict]:
    """Read head and tail of a JSONL file for efficient metadata extraction."""
    fp = Path(file_path)
    try:
        if not fp.exists():
            return []

        file_size = fp.stat().st_size
        with open(fp, "rb") as f:
            head_size = min(HEAD_BYTES, file_size)
            head_str = f.read(head_size).decode("utf-8", errors="replace")
            head_lines = head_str.split("\n")
            if head_size < file_size:
                head_lines.pop()

            records = _parse_jsonl_lines(head_lines)

            if file_size > HEAD_BYTES + TAIL_BYTES:
                f.seek(file_size - TAIL_BYTES)
                tail_str = f.read(TAIL_BYTES).decode("utf-8", errors="replace")
                tail_lines = tail_str.split("\n")
                tail_lines.pop(0)
                records.extend(_parse_jsonl_lines(tail_lines))

        return records
    except Exception:
        return []


def _format_timestamp(st: Any, attr: str) -> str | None:
    """Format a stat timestamp attribute as an ISO-8601 Z string."""
    if not st:
        return None
    ts = getattr(st, attr, None)
    if ts is None:
        return None
    return (
        datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    )


def _parse_memory_file(
    file_path: Path,
    project_name: str,
    file_name: str,
) -> dict[str, Any] | None:
    """Parse a single memory .md file into a metadata dict."""
    content = read_text_file(file_path)
    if not content:
        return None

    st = stat_file(file_path)
    parsed = parse_yaml_frontmatter(content)
    meta = parsed["meta"]

    return {
        "file": file_name,
        "path": str(file_path),
        "project": project_name,
        "name": meta.get("name") or file_name.replace(".md", ""),
        "description": meta.get("description") or "",
        "type": meta.get("type") or "unknown",
        "body": parsed["body"],
        "modifiedAt": _format_timestamp(st, "st_mtime"),
        "createdAt": _format_timestamp(st, "st_ctime"),
    }


def discover_all_memories() -> list[dict[str, Any]]:
    """Discover all memory files across Claude project directories."""
    projects_dir = CLAUDE_DIR / "projects"
    entries = list_dir(projects_dir, with_file_types=True)
    if not entries:
        return []

    memories: list[dict[str, Any]] = []

    for pdir in entries:
        if not pdir.is_dir():
            continue

        memory_dir = projects_dir / pdir.name / "memory"
        files = list_dir(memory_dir)
        if not files:
            continue

        for file_name in files:
            if not file_name.endswith(".md") or file_name == "MEMORY.md":
                continue
            try:
                result = _parse_memory_file(
                    memory_dir / file_name, pdir.name, file_name
                )
                if result:
                    memories.append(result)
            except Exception as e:
                print(
                    f"[methodology-agent] Failed to read {memory_dir / file_name}: {e}",
                    file=sys.stderr,
                )

    return memories


def _parse_conversation_file(
    file_path: Path,
    project_name: str,
    fallback_id: str,
) -> dict[str, Any] | None:
    """Parse a single JSONL conversation file. Returns record or None."""
    raw_records = read_head_tail(file_path)
    if not raw_records:
        return None

    meta = extract_metadata_fields(raw_records)
    stats = extract_message_stats(raw_records)

    if stats["user_count"] + stats["assistant_count"] == 0:
        return None

    return build_conversation_record(meta, stats, file_path, project_name, fallback_id)


def discover_conversations() -> list[dict[str, Any]]:
    """Discover all conversation JSONL files across Claude project directories."""
    projects_dir = CLAUDE_DIR / "projects"
    entries = list_dir(projects_dir, with_file_types=True)
    if not entries:
        return []

    conversations: list[dict[str, Any]] = []

    for pdir in entries:
        if not pdir.is_dir():
            continue

        proj_path = projects_dir / pdir.name
        proj_entries = list_dir(proj_path, with_file_types=True)
        if not proj_entries:
            continue

        for entry in proj_entries:
            if not entry.is_file() or not entry.name.endswith(".jsonl"):
                continue
            if "subagent" in entry.name:
                continue
            file_path = proj_path / entry.name
            if "subagents" in str(file_path):
                continue

            try:
                record = _parse_conversation_file(
                    file_path, pdir.name, entry.name.replace(".jsonl", "")
                )
                if record:
                    conversations.append(record)
            except Exception as e:
                print(
                    f"[methodology-agent] Failed to read conversation {file_path}: {e}",
                    file=sys.stderr,
                )

    return conversations


def group_by_project(conversations: list[dict]) -> dict[str, list[dict]]:
    """Group conversation metadata by project ID."""
    groups: dict[str, list[dict]] = {}
    for conv in conversations:
        proj = conv.get("project", "")
        if proj not in groups:
            groups[proj] = []
        groups[proj].append(conv)
    return groups
