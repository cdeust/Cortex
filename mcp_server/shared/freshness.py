"""Freshness annotation for injected memories (fleet-watch #110).

The harness-comparison rev.2 A/B measured the ai-architect stack (Harness B)
serving facts "2-4 months stale with no age signal": every recalled memory
entered the model's context as bare text, so a fresh fact and a months-old one
were indistinguishable. This module renders the freshness the store *already*
tracks -- ``created_at``, the ``source_attribution`` provenance grade, and
``is_stale`` -- as a compact suffix the injection formatters append per memory.

Pure: a memory dict plus an explicit ``now`` in, an annotation string out. The
caller owns the clock, so the output is deterministic and testable. A memory
that carries none of the three signals yields "" -- callers append nothing, so
bare-memory call sites are unaffected.
"""

from __future__ import annotations

from datetime import datetime, timezone

# Calendar/SI time-unit boundaries, in seconds. These are unit *definitions*
# (a minute is 60 s, a day 86400 s), not tuned parameters; month and year use
# the conventional 30-day / 365-day display approximations.
# source: calendar arithmetic (SI second; 30-day month / 365-day year display
#   convention).
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
