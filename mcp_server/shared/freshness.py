"""Freshness annotation for injected memories.

source: ADR-0649
"""

from __future__ import annotations

from datetime import datetime, timezone

# source: ADR-0649

# source: ADR-0649
_MINUTE = 60
_HOUR = 60 * _MINUTE
_DAY = 24 * _HOUR
_MONTH = 30 * _DAY
_YEAR = 365 * _DAY

_SEP = "  ·  "


def _coerce(value: object) -> datetime | None:
    """A tz-aware datetime from a datetime or ISO-8601 string, else None."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def humanize_age(created: object, now: datetime) -> str:
    """Compact relative age: "just now", "3d ago", "5mo ago". "" if unknown."""
    dt = _coerce(created)
    if dt is None:
        return ""
    secs = (now - dt).total_seconds()
    if secs < _MINUTE:
        return "just now"
    if secs < _HOUR:
        return f"{int(secs // _MINUTE)}m ago"
    if secs < _DAY:
        return f"{int(secs // _HOUR)}h ago"
    if secs < _MONTH:
        return f"{int(secs // _DAY)}d ago"
    if secs < _YEAR:
        return f"{int(secs // _MONTH)}mo ago"
    return f"{int(secs // _YEAR)}y ago"


def provenance_suffix(memory: dict, now: datetime) -> str:
    """Age · provenance-grade · stale marker for one injected memory.

    Empty parts are omitted. A memory with no ``created_at``, an "unknown"
    grade, and no stale flag yields "".
    """
    parts: list[str] = []
    age = humanize_age(memory.get("created_at"), now)
    if age:
        parts.append(age)
    grade = str(memory.get("source_attribution") or "").strip().lower()
    if grade and grade != "unknown":
        parts.append(f"src={grade}")
    if memory.get("is_stale"):
        parts.append("⚠stale")
    return _SEP.join(parts)
