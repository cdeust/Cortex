"""Handler: get_project_story — period-based autobiographical narrative.

Distinct from the 'narrative' handler which produces a generic project summary.
get_project_story produces a time-bounded, chronological story of what happened
in a project, structured as chapters by time period.

Periods: day, week, month, all
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

# ── Schema ────────────────────────────────────────────────────────────────────

schema = {
    "description": "Generate a period-based autobiographical narrative of project activity. Returns chronological 'chapters' of what happened during a time period.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Project directory to narrate",
            },
            "domain": {
                "type": "string",
                "description": "Domain to narrate (alternative to directory)",
            },
            "period": {
                "type": "string",
                "enum": ["day", "week", "month", "all"],
                "description": "Time window for the story (default: week)",
            },
            "max_chapters": {
                "type": "integer",
                "description": "Max number of time-bucketed chapters (default 5)",
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


def _parse_dt(iso_str: str) -> datetime | None:
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _period_cutoff(period: str) -> datetime:
    now = datetime.now(timezone.utc)
    if period == "day":
        return now - timedelta(days=1)
    elif period == "week":
        return now - timedelta(weeks=1)
    elif period == "month":
        return now - timedelta(days=30)
    else:  # "all"
        return datetime(2000, 1, 1, tzinfo=timezone.utc)


def _bucket_label(dt: datetime, period: str) -> str:
    """Return a human-readable bucket label for a datetime."""
    if period == "day":
        return dt.strftime("%H:00")
    elif period == "week":
        return dt.strftime("%A %b %d")
    elif period == "month":
        return dt.strftime("Week of %b %d")
    else:
        return dt.strftime("%B %Y")


def _bucket_key(dt: datetime, period: str) -> str:
    """Sortable bucket key."""
    if period == "day":
        return dt.strftime("%Y%m%d%H")
    elif period == "week":
        return dt.strftime("%Y%m%d")
    elif period == "month":
        year, week, _ = dt.isocalendar()
        return f"{year}{week:02d}"
    else:
        return dt.strftime("%Y%m")


def _extract_headline(text: str) -> str:
    """Extract a short headline from memory content."""
    text = text.strip()
    match = re.match(r"^([^.!?\n]{10,100})[.!?\n]", text)
    if match:
        return match.group(1).strip()
    return text[:80].strip()


_DECISION_RE = re.compile(
    r"\b(decided|chose|switched|migrated|using|adopted|replaced|fixed|resolved|deployed)\b",
    re.IGNORECASE,
)


def _memory_to_chapter_entry(mem: dict[str, Any]) -> dict[str, Any]:
    content = mem.get("content", "")
    is_decision = bool(_DECISION_RE.search(content))
    return {
        "memory_id": mem["id"],
        "headline": _extract_headline(content),
        "importance": round(mem.get("importance", 0.5), 3),
        "heat": round(mem.get("heat", 0.0), 3),
        "is_decision": is_decision,
        "tags": mem.get("tags", []),
    }


def _empty_story(period: str, message: str) -> dict[str, Any]:
    """Return a no-result response."""
    return {
        "period": period,
        "chapters": [],
        "total_memories": 0,
        "story": message,
    }


def _fetch_memories(
    store: MemoryStore,
    directory: str,
    domain: str,
) -> list[dict[str, Any]]:
    """Fetch memories scoped by directory, domain, or global heat."""
    if directory:
        return store.get_memories_for_directory(directory, min_heat=0.0)
    if domain:
        return store.get_memories_for_domain(domain, min_heat=0.0, limit=500)
    return store.get_hot_memories(min_heat=0.05, limit=500)


def _filter_by_period(
    memories: list[dict[str, Any]],
    period: str,
) -> list[dict[str, Any]]:
    """Keep only memories within the period cutoff, attaching _dt."""
    cutoff = _period_cutoff(period)
    filtered = []
    for mem in memories:
        dt = _parse_dt(mem.get("created_at", ""))
        if dt and dt >= cutoff:
            mem["_dt"] = dt
            filtered.append(mem)
    return filtered


def _build_chapter(key: str, mems: list[dict], period: str) -> dict[str, Any]:
    """Build a single chapter dict from a bucket of memories."""
    mems_sorted = sorted(mems, key=lambda m: m.get("importance", 0), reverse=True)
    label = _bucket_label(mems_sorted[0]["_dt"], period)
    entries = [_memory_to_chapter_entry(m) for m in mems_sorted[:10]]
    decisions = [e for e in entries if e["is_decision"]]
    return {
        "label": label,
        "bucket_key": key,
        "memory_count": len(mems),
        "entries": entries,
        "decision_count": len(decisions),
        "highlight": entries[0]["headline"] if entries else "",
    }


def _build_story(chapters: list[dict[str, Any]]) -> str:
    """Build a one-paragraph story from chapter highlights."""
    sentences = []
    for ch in chapters:
        headlines = [e["headline"] for e in ch["entries"][:3]]
        sentences.append(f"{ch['label']}: {'; '.join(headlines[:2])}.")
    return " ".join(sentences)


# ── Handler ───────────────────────────────────────────────────────────────────


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Generate period-based autobiographical narrative."""
    args = args or {}
    directory = args.get("directory", "")
    domain = args.get("domain", "")
    period = args.get("period", "week")
    max_chapters = int(args.get("max_chapters", 5))

    if period not in ("day", "week", "month", "all"):
        period = "week"

    store = _get_store()
    memories = _fetch_memories(store, directory, domain)
    if not memories:
        return _empty_story(period, "No memories found for this period.")

    filtered = _filter_by_period(memories, period)
    if not filtered:
        return _empty_story(period, f"No memories found within the last {period}.")

    # Bucket into chapters
    buckets: dict[str, list[dict]] = {}
    for mem in filtered:
        key = _bucket_key(mem["_dt"], period)
        buckets.setdefault(key, []).append(mem)

    sorted_keys = sorted(buckets.keys())[-max_chapters:]
    chapters = [_build_chapter(key, buckets[key], period) for key in sorted_keys]

    return {
        "period": period,
        "chapters": chapters,
        "total_memories": len(filtered),
        "story": _build_story(chapters),
    }
