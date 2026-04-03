"""Pure session grouping logic for temporal memory browsing.

Groups memories into sessions by session_id or temporal proximity.
No I/O — operates on in-memory data structures.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def group_into_sessions(
    memories: list[dict],
    window_hours: float = 2.0,
) -> list[dict]:
    """Group memories into sessions by session_id or temporal proximity.

    If memories have a session_id, group by that. Otherwise, cluster
    by temporal proximity (memories within window_hours of each other).

    Returns list of session dicts sorted by most recent first.
    """
    by_session: dict[str, list[dict]] = {}

    # Separate memories with and without session_id
    unassigned: list[dict] = []
    for mem in memories:
        sid = mem.get("session_id", "")
        if sid:
            by_session.setdefault(sid, []).append(mem)
        else:
            unassigned.append(mem)

    # Group unassigned by temporal proximity
    if unassigned:
        temporal_groups = _cluster_by_time(unassigned, window_hours)
        for group in temporal_groups:
            sid = _derive_session_id(group)
            by_session.setdefault(sid, []).extend(group)

    # Build session summaries
    sessions = []
    for sid, mems in by_session.items():
        mems.sort(key=lambda m: m.get("created_at", ""))
        sessions.append(_build_session_dict(sid, mems))

    # Sort by most recent session first
    sessions.sort(key=lambda s: s["last_at"], reverse=True)
    return sessions


def compute_session_summary(memories: list[dict]) -> str:
    """Generate a one-line summary from a session's memories.

    Joins the first 3 content snippets (truncated to 60 chars each).
    """
    snippets = []
    for mem in memories[:3]:
        content = mem.get("content", "")
        snippet = content[:60].replace("\n", " ").strip()
        if snippet:
            snippets.append(snippet)
    return " | ".join(snippets) if snippets else "Empty session"


def _cluster_by_time(
    memories: list[dict],
    window_hours: float,
) -> list[list[dict]]:
    """Cluster memories by temporal proximity."""
    if not memories:
        return []

    sorted_mems = sorted(memories, key=lambda m: m.get("created_at", ""))
    window = timedelta(hours=window_hours)
    groups: list[list[dict]] = [[sorted_mems[0]]]

    for mem in sorted_mems[1:]:
        prev_time = _parse_time(groups[-1][-1].get("created_at", ""))
        curr_time = _parse_time(mem.get("created_at", ""))
        if prev_time and curr_time and (curr_time - prev_time) <= window:
            groups[-1].append(mem)
        else:
            groups.append([mem])

    return groups


def _derive_session_id(memories: list[dict]) -> str:
    """Derive a session_id from the earliest memory's timestamp."""
    if not memories:
        return "unknown"
    earliest = memories[0].get("created_at", "")
    ts = _parse_time(earliest)
    if ts:
        return ts.strftime("%Y-%m-%dT%H")
    return f"group-{id(memories)}"


def _parse_time(ts: str | datetime | None) -> datetime | None:
    """Parse ISO timestamp string to datetime."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    try:
        # Handle both with and without timezone
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _build_session_dict(session_id: str, memories: list[dict]) -> dict:
    """Build a session summary dict from grouped memories."""
    domains = set()
    for m in memories:
        d = m.get("domain", "")
        if d:
            domains.add(d)

    first_at = memories[0].get("created_at", "")
    last_at = memories[-1].get("created_at", "")

    return {
        "session_id": session_id,
        "memory_count": len(memories),
        "first_at": str(first_at),
        "last_at": str(last_at),
        "domains": sorted(domains),
        "summary": compute_session_summary(memories),
    }
