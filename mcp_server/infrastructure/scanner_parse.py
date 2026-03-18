"""Conversation record parsing helpers for the scanner module.

Extracts metadata, message statistics, and assembles conversation records
from raw JSONL records. Separated from scanner.py to stay under 300 lines.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from mcp_server.infrastructure.file_io import stat_file
from mcp_server.shared.text import extract_keywords


def extract_user_text(content: Any) -> str:
    """Extract text from a user message content field."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def extract_metadata_fields(raw_records: list[dict]) -> dict[str, Any]:
    """Extract session-level metadata from raw JSONL records."""
    session_id = None
    slug = None
    cwd = None
    first_timestamp = None
    last_timestamp = None

    for rec in raw_records:
        if rec.get("sessionId") and not session_id:
            session_id = rec["sessionId"]
        if rec.get("slug") and not slug:
            slug = rec["slug"]
        if rec.get("cwd") and not cwd:
            cwd = rec["cwd"]

        ts = rec.get("timestamp")
        if ts:
            if not first_timestamp or ts < first_timestamp:
                first_timestamp = ts
            if not last_timestamp or ts > last_timestamp:
                last_timestamp = ts

    return {
        "session_id": session_id,
        "slug": slug,
        "cwd": cwd,
        "first_timestamp": first_timestamp,
        "last_timestamp": last_timestamp,
    }


def _extract_tools_from_content(content: Any, tools_used: set[str]) -> None:
    """Extract tool names from assistant message content blocks."""
    if isinstance(content, list):
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                and block.get("name")
            ):
                tools_used.add(block["name"])


def extract_message_stats(raw_records: list[dict]) -> dict[str, Any]:
    """Extract per-message statistics: counts, tools, text content."""
    user_count = 0
    assistant_count = 0
    tools_used: set[str] = set()
    first_message = None
    all_text_parts: list[str] = []
    all_text_len = 0

    for rec in raw_records:
        if rec.get("type") == "user":
            user_count += 1
            msg = rec.get("message") or {}
            content = msg.get("content")
            if content and not rec.get("isMeta") and not rec.get("toolUseResult"):
                text = extract_user_text(content)
                if text and not text.startswith("[Request interrupted"):
                    if not first_message:
                        first_message = text
                    if all_text_len < 4000:
                        chunk = text[: 4000 - all_text_len]
                        all_text_parts.append(chunk)
                        all_text_len += len(chunk)

        if rec.get("type") == "assistant":
            assistant_count += 1
            _extract_tools_from_content(
                (rec.get("message") or {}).get("content"), tools_used
            )

    return {
        "user_count": user_count,
        "assistant_count": assistant_count,
        "tools_used": tools_used,
        "first_message": first_message,
        "all_text": " ".join(all_text_parts) or None,
    }


def compute_duration(first_ts: str | None, last_ts: str | None) -> int | None:
    """Compute session duration in milliseconds from ISO timestamps."""
    if not first_ts or not last_ts:
        return None
    try:
        t1 = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
        t2 = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
        return int((t2 - t1).total_seconds() * 1000)
    except Exception:
        return None


def build_conversation_record(
    meta: dict,
    stats: dict,
    file_path: Path,
    project_name: str,
    fallback_id: str,
) -> dict[str, Any]:
    """Assemble a conversation record from extracted metadata and stats."""
    session_id = meta["session_id"] or fallback_id
    all_text = stats["all_text"]
    st = stat_file(file_path)

    return {
        "sessionId": session_id,
        "slug": meta["slug"],
        "project": project_name,
        "cwd": meta["cwd"],
        "firstMessage": stats["first_message"],
        "allText": all_text,
        "keywords": extract_keywords(all_text or ""),
        "startedAt": meta["first_timestamp"],
        "endedAt": meta["last_timestamp"],
        "messageCount": stats["user_count"] + stats["assistant_count"],
        "userCount": stats["user_count"],
        "assistantCount": stats["assistant_count"],
        "turnCount": stats["assistant_count"],
        "toolsUsed": list(stats["tools_used"]),
        "duration": compute_duration(meta["first_timestamp"], meta["last_timestamp"]),
        "fileSize": st.st_size if st else None,
    }
