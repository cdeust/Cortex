"""Temporal scoring: date parsing, proximity, distance decay, recency boost.

Recency formula from ai-architect: boost = 0.15 * exp(-days/30), cutoff 90 days.
Date distance uses exponential decay (closer dates score higher).

Pure business logic -- no I/O.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone


_MONTH_NAMES = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

_TEMPORAL_QUERY_RE = re.compile(
    r"\b(when|date|time|ago|before|after|during|"
    r"january|february|march|april|may|june|july|august|"
    r"september|october|november|december|"
    r"yesterday|today|last|recent|week|month|year|"
    r"\d{1,2}\s+\w+\s+\d{4}|\d{4}-\d{2}-\d{2})\b",
    re.IGNORECASE,
)

_DATE_PATTERNS = [
    re.compile(r"(\d{4}-\d{2}-\d{2})"),
    re.compile(
        r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+(\d{4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+(\d{4})",
        re.IGNORECASE,
    ),
    re.compile(r"\[Date:\s*([^\]]+)\]"),
]


def is_temporal_query(query: str) -> bool:
    """Detect temporal intent in a query."""
    return len(_TEMPORAL_QUERY_RE.findall(query)) >= 1


def extract_date_hints(text: str) -> list[str]:
    """Extract date/month mentions from text."""
    hints: set[str] = set()
    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(text):
            hints.add(match.group(0).strip())
    for month in _MONTH_NAMES:
        if month in text.lower():
            hints.add(month)
    return list(hints)


def compute_temporal_proximity(
    doc_text: str,
    date_hints: list[str],
) -> float:
    """Score document by date-hint overlap. 1.0=exact, 0.5=partial, 0.0=none."""
    if not date_hints:
        return 0.0
    doc_lower = doc_text.lower()
    score = 0.0
    for hint in date_hints:
        hint_lower = hint.lower()
        if hint_lower in doc_lower:
            score = max(score, 1.0)
        elif any(p in doc_lower for p in hint_lower.split() if len(p) > 3):
            score = max(score, 0.5)
    return score


_DD_MONTH_YYYY_RE = re.compile(
    r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+(\d{4})",
    re.IGNORECASE,
)
_MONTH_DD_YYYY_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})",
    re.IGNORECASE,
)
_EMBEDDED_ISO_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _try_parse_named_date(date_str: str) -> datetime | None:
    """Try DD Month YYYY and Month DD, YYYY formats."""
    m = _DD_MONTH_YYYY_RE.match(date_str)
    if m:
        try:
            return datetime(
                int(m.group(3)), _MONTH_NAMES[m.group(2).lower()], int(m.group(1))
            )
        except (ValueError, KeyError):
            pass
    m = _MONTH_DD_YYYY_RE.match(date_str)
    if m:
        try:
            return datetime(
                int(m.group(3)), _MONTH_NAMES[m.group(1).lower()], int(m.group(2))
            )
        except (ValueError, KeyError):
            pass
    m = _EMBEDDED_ISO_RE.search(date_str)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return None


def parse_date(date_str: str) -> datetime | None:
    """Parse date from ISO 8601, named month formats, or embedded ISO."""
    if not date_str:
        return None
    date_str = date_str.strip()
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00").split("T")[0])
    except (ValueError, AttributeError):
        pass
    return _try_parse_named_date(date_str)


def compute_date_distance_score(
    doc_date_str: str,
    target_date_hints: list[str],
    scale_days: float = 14.0,
) -> float:
    """Exponential decay distance between document date and target date.

    Closer dates score higher. Used for temporal retrieval queries.
    """
    if not doc_date_str or not target_date_hints:
        return 0.0

    doc_dt = parse_date(doc_date_str)
    if not doc_dt:
        return 0.0

    best_score = 0.0
    for hint in target_date_hints:
        target_dt = parse_date(hint)
        if target_dt:
            delta_days = abs((doc_dt - target_dt).total_seconds()) / 86400.0
            score = math.exp(-delta_days / scale_days)
            best_score = max(best_score, score)

    return best_score


def compute_recency_boost(
    created_at: str | datetime | None,
    boost_max: float = 0.15,
    halflife_days: float = 30.0,
    cutoff_days: float = 90.0,
) -> float:
    """Exponential recency boost (ai-architect formula).

    Formula: boost = boost_max * exp(-age * ln(2) / halflife)
    """
    if not created_at:
        return 0.0
    now = datetime.now(timezone.utc)
    if isinstance(created_at, str):
        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return 0.0
    elif isinstance(created_at, datetime):
        dt = created_at
    else:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age_days = (now - dt).total_seconds() / 86400.0
    if age_days < 0 or age_days > cutoff_days:
        return 0.0
    return boost_max * math.exp(-math.log(2.0) / halflife_days * age_days)
