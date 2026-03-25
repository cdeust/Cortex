"""Prospective memory — future-oriented triggers that fire on matching context.

"Remember to do X when Y happens" — the ability to remember intentions.

Trigger types:
  - directory_match: fires when working in a specific directory
  - keyword_match: fires when content contains specific keywords
  - entity_match: fires when specific entities appear
  - time_based: fires at specific times (HH:MM or weekday:N)

Auto-extraction detects prospective intent from natural language:
  - "TODO: ...", "FIXME: ...", "remember to ...", "next time ..."
  - "don't forget ...", "when we ...", "later ...", "should also ..."

Pure business logic — no I/O.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

VALID_TRIGGER_TYPES = frozenset(
    {
        "directory_match",
        "keyword_match",
        "entity_match",
        "time_based",
    }
)

# Future-oriented phrases that signal prospective intent
_PROSPECTIVE_PATTERNS = [
    (re.compile(r"\bTODO\b[:\s]*(.+?)(?:\n|$)", re.IGNORECASE), "keyword_match"),
    (re.compile(r"\bFIXME\b[:\s]*(.+?)(?:\n|$)", re.IGNORECASE), "keyword_match"),
    (re.compile(r"remember to\s+(.+?)(?:\.|$)", re.IGNORECASE), "keyword_match"),
    (re.compile(r"don'?t forget\s+(.+?)(?:\.|$)", re.IGNORECASE), "keyword_match"),
    (re.compile(r"next time\s+(.+?)(?:\.|$)", re.IGNORECASE), "keyword_match"),
    (re.compile(r"when we\s+(.+?)(?:\.|$)", re.IGNORECASE), "keyword_match"),
    (re.compile(r"later\s+(.+?)(?:\.|$)", re.IGNORECASE), "keyword_match"),
    (re.compile(r"eventually\s+(.+?)(?:\.|$)", re.IGNORECASE), "keyword_match"),
    (re.compile(r"should also\s+(.+?)(?:\.|$)", re.IGNORECASE), "keyword_match"),
    # Standing instructions: "Always X when I ask about Y"
    (
        re.compile(
            r"always\s+(.+?)\s+when\s+(?:i|you)\s+(?:ask|mention|discuss|talk)\b.+",
            re.IGNORECASE,
        ),
        "keyword_match",
    ),
    # Preference constraints: "Prefer X over Y", "Use X instead of Y"
    (
        re.compile(
            r"(?:always|prefer)\s+(?:use|prefer)\s+(.+?)(?:\.|$)", re.IGNORECASE
        ),
        "keyword_match",
    ),
    (re.compile(r"make sure (?:to\s+)?(.+?)(?:\.|$)", re.IGNORECASE), "keyword_match"),
]

_TIME_HOUR_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_TIME_WEEKDAY_RE = re.compile(r"^weekday:(\d)$")

_STOP_WORDS = frozenset({"the", "and", "for", "with", "that", "this", "from"})


def extract_prospective_intents(content: str) -> list[dict[str, str]]:
    """Scan content for future-oriented phrases.

    Returns list of {content, trigger_condition, trigger_type} dicts.
    """
    results = []
    for pattern, trigger_type in _PROSPECTIVE_PATTERNS:
        for match in pattern.finditer(content):
            actionable = match.group(1).strip()
            if not actionable or len(actionable) < 5:
                continue

            keywords = " ".join(
                w
                for w in actionable.split()
                if len(w) > 2 and w.lower() not in _STOP_WORDS
            )
            if not keywords:
                continue

            results.append(
                {
                    "content": actionable,
                    "trigger_condition": keywords,
                    "trigger_type": trigger_type,
                }
            )
    return results


def check_trigger(
    trigger: dict,
    *,
    directory: str = "",
    content: str = "",
    entities: list[str] | None = None,
    current_time: datetime | None = None,
) -> bool:
    """Check if a single trigger matches the given context."""
    trigger_type = trigger.get("trigger_type", "")
    condition = trigger.get("trigger_condition", "")

    if trigger_type == "directory_match":
        target = trigger.get("target_directory") or condition
        return target != "" and target in directory

    if trigger_type == "keyword_match":
        keywords = condition.lower().split()
        content_lower = content.lower()
        return any(kw in content_lower for kw in keywords)

    if trigger_type == "entity_match":
        entity_name = condition.lower()
        return any(entity_name == e.lower() for e in (entities or []))

    if trigger_type == "time_based":
        return _matches_time(condition, current_time or datetime.now(timezone.utc))

    return False


def _matches_time(condition: str, current_time: datetime) -> bool:
    """Check if current_time matches a cron-like time condition."""
    m = _TIME_HOUR_RE.match(condition)
    if m:
        return current_time.hour == int(m.group(1)) and current_time.minute == int(
            m.group(2)
        )

    m = _TIME_WEEKDAY_RE.match(condition)
    if m:
        return current_time.weekday() == int(m.group(1))

    return False
