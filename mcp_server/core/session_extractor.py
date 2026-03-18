"""Extract memorable content from conversation JSONL records.

Pure business logic — no I/O. Receives parsed records, returns extraction results.

Strategies:
  1. Decision extraction: user messages containing decision keywords
  2. Error extraction: messages about bugs, failures, debugging sessions
  3. Architecture extraction: design discussions, pattern choices
  4. Key insight extraction: important conclusions, lessons learned
  5. Tool pattern extraction: which tools were used and how

Each extracted item includes content, tags, and a source classification.
"""

from __future__ import annotations

import re
from typing import Any

# ── Detection patterns ────────────────────────────────────────────────────

_DECISION_RE = re.compile(
    r"\b(decided|chose|switched|migrated|selected|picked|opted|"
    r"going with|let'?s use|we should|must use|prefer|"
    r"instead of|rather than|moved to|changed to)\b",
    re.IGNORECASE,
)

_ERROR_RE = re.compile(
    r"\b(error|exception|traceback|failed|failure|bug|crash|"
    r"broken|timeout|denied|rejected|not working|doesn'?t work|"
    r"fix|fixed|resolved|debug|issue)\b",
    re.IGNORECASE,
)

_ARCHITECTURE_RE = re.compile(
    r"\b(architecture|design|pattern|refactor|restructur|modular|"
    r"decouple|abstract|layer|interface|protocol|clean architecture|"
    r"solid|dependency injection|factory|observer|singleton)\b",
    re.IGNORECASE,
)

_INSIGHT_RE = re.compile(
    r"\b(learned|realized|turns out|key takeaway|important|"
    r"remember|note to self|lesson|discovery|root cause|"
    r"the problem was|solution is|conclusion)\b",
    re.IGNORECASE,
)

_SKIP_RE = re.compile(
    r"^\[Request interrupted|^<system-reminder>|^Continue the conversation|"
    r"^<task-notification>|^<tool-use-result>",
    re.IGNORECASE,
)

# Minimum content length worth storing
_MIN_CONTENT_LEN = 40
# Maximum content length per memory
_MAX_CONTENT_LEN = 2000


# ── Public API ────────────────────────────────────────────────────────────


def extract_user_messages(records: list[dict]) -> list[dict[str, Any]]:
    """Extract user messages from JSONL records, filtering noise."""
    messages: list[dict[str, Any]] = []
    for rec in records:
        if rec.get("type") != "user":
            continue
        if rec.get("isMeta") or rec.get("toolUseResult"):
            continue

        msg = rec.get("message") or {}
        content = msg.get("content", "")
        text = _extract_text(content)

        if not text or len(text) < _MIN_CONTENT_LEN:
            continue
        if _SKIP_RE.search(text):
            continue

        messages.append(
            {
                "text": text[:_MAX_CONTENT_LEN],
                "timestamp": rec.get("timestamp", ""),
                "session_id": rec.get("sessionId", ""),
            }
        )

    return messages


def classify_message(text: str) -> list[str]:
    """Classify a message into zero or more categories."""
    categories: list[str] = []

    if _DECISION_RE.search(text):
        categories.append("decision")
    if _ERROR_RE.search(text):
        categories.append("error")
    if _ARCHITECTURE_RE.search(text):
        categories.append("architecture")
    if _INSIGHT_RE.search(text):
        categories.append("insight")

    return categories


def score_importance(text: str, categories: list[str]) -> float:
    """Score how important a message is for long-term memory."""
    score = 0.3  # baseline

    # Category boosts
    if "decision" in categories:
        score += 0.25
    if "architecture" in categories:
        score += 0.2
    if "error" in categories:
        score += 0.15
    if "insight" in categories:
        score += 0.3

    # Content signals
    if len(text) > 200:
        score += 0.1
    if re.search(r"```", text):
        score += 0.05  # contains code
    if re.search(r"\b(always|never|must|should)\b", text, re.IGNORECASE):
        score += 0.1  # prescriptive

    return min(score, 1.0)


def _classify_and_build_item(msg: dict, min_importance: float) -> dict[str, Any] | None:
    """Classify a message and build a memorable item if important enough."""
    text = msg["text"]
    categories = classify_message(text)
    importance = score_importance(text, categories)
    if importance < min_importance:
        return None
    return {
        "content": text,
        "tags": list(categories) + ["imported"],
        "importance": importance,
        "timestamp": msg["timestamp"],
        "session_id": msg["session_id"],
    }


def extract_memorable_items(
    records: list[dict],
    *,
    min_importance: float = 0.4,
) -> list[dict[str, Any]]:
    """Extract items worth remembering from conversation records.

    Returns list of dicts with: content, tags, importance, timestamp, session_id.
    Filters by minimum importance threshold.
    """
    messages = extract_user_messages(records)
    items: list[dict[str, Any]] = []
    seen_content: set[str] = set()

    for msg in messages:
        content_key = msg["text"][:100].lower()
        if content_key in seen_content:
            continue
        seen_content.add(content_key)

        item = _classify_and_build_item(msg, min_importance)
        if item is not None:
            items.append(item)

    return items


def _extract_tools_from_assistant(rec: dict, tools_used: set[str]) -> None:
    """Extract tool names from an assistant record."""
    msg = rec.get("message", {})
    content = msg.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                name = block.get("name", "")
                if name:
                    tools_used.add(name)


def extract_session_summary(records: list[dict]) -> dict[str, Any]:
    """Build a session-level summary from records."""
    session_id = ""
    cwd = ""
    first_message = ""
    timestamps: list[str] = []
    user_count = 0
    tools_used: set[str] = set()

    for rec in records:
        if not session_id and rec.get("sessionId"):
            session_id = rec["sessionId"]
        if not cwd and rec.get("cwd"):
            cwd = rec["cwd"]

        ts = rec.get("timestamp")
        if ts:
            timestamps.append(ts)

        if rec.get("type") == "user":
            user_count += 1
            if not first_message and not rec.get("toolUseResult"):
                msg = rec.get("message", {})
                text = _extract_text(msg.get("content", ""))
                if text and not _SKIP_RE.search(text):
                    first_message = text[:200]

        if rec.get("type") == "assistant":
            _extract_tools_from_assistant(rec, tools_used)

    return {
        "session_id": session_id,
        "cwd": cwd,
        "first_message": first_message,
        "user_count": user_count,
        "tools_used": sorted(tools_used),
        "start_time": min(timestamps) if timestamps else "",
        "end_time": max(timestamps) if timestamps else "",
    }


# ── Helpers ───────────────────────────────────────────────────────────────


def _extract_text(content: Any) -> str:
    """Extract plain text from message content (str or list of blocks)."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return " ".join(parts).strip()
    return ""
