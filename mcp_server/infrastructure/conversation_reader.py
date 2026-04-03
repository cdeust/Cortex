"""On-demand full JSONL conversation reader.

Reads entire conversation files line-by-line (streaming) and transforms
raw records into clean message objects for display.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_full_conversation(file_path: str | Path) -> list[dict[str, Any]]:
    """Read entire JSONL file, return all records as dicts.

    Streams line-by-line to handle large files without loading
    the full content into memory at once.
    """
    fp = Path(file_path)
    if not fp.exists():
        return []

    records: list[dict[str, Any]] = []
    try:
        with open(fp, encoding="utf-8", errors="replace") as f:
            for line in f:
                trimmed = line.strip()
                if not trimmed:
                    continue
                try:
                    records.append(json.loads(trimmed))
                except (json.JSONDecodeError, ValueError):
                    pass
    except OSError:
        return []

    return records


def _extract_text(content: Any) -> str:
    """Extract plain text from a message content field."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return " ".join(parts)
    return ""


def _extract_tool_calls(content: Any) -> list[dict[str, str]]:
    """Extract tool_use blocks from assistant message content."""
    if not isinstance(content, list):
        return []
    calls: list[dict[str, str]] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            calls.append(
                {
                    "name": block.get("name", ""),
                    "input": str(block.get("input", "")),
                    "output": str(block.get("output", "")),
                }
            )
    return calls


def _is_skippable(rec: dict[str, Any]) -> bool:
    """Check if a record should be filtered out."""
    if rec.get("type") == "system":
        return True
    if rec.get("isMeta"):
        return True
    if rec.get("type") == "user" and rec.get("toolUseResult"):
        return True
    if rec.get("permissionMode"):
        return True
    return False


def format_conversation_messages(
    raw_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Transform raw JSONL records into clean message objects.

    Returns list of:
    {
        "role": "user" | "assistant",
        "text": str,
        "timestamp": str | None,
        "toolCalls": [{"name": str, "input": str, "output": str}]
    }
    """
    messages: list[dict[str, Any]] = []

    for rec in raw_records:
        if _is_skippable(rec):
            continue

        rec_type = rec.get("type")
        if rec_type not in ("user", "assistant"):
            continue

        msg = rec.get("message") or {}
        content = msg.get("content")
        if content is None:
            continue

        text = _extract_text(content)
        timestamp = rec.get("timestamp")
        entry: dict[str, Any] = {
            "role": rec_type,
            "text": text,
            "timestamp": timestamp,
        }

        if rec_type == "assistant":
            tool_calls = _extract_tool_calls(content)
            entry["toolCalls"] = tool_calls
        else:
            entry["toolCalls"] = []

        messages.append(entry)

    return messages
