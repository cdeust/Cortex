"""SessionStart hook PostgreSQL memory fetching: anchors, team decisions, hot memories.

source: ADR-0498"""

from __future__ import annotations

import json

from mcp_server.hooks.session_start_common import (
    _ANCHOR_LIMIT,
    _HOT_LIMIT,
    _MIN_HEAT,
    _log,
)
from mcp_server.infrastructure.hook_queries import (
    session_anchor_rows,
    session_hot_rows,
    session_team_decision_rows,
)
from mcp_server.shared.project_scope import memory_matches_project, project_ancestors


def _banner_entry(r: dict, **extra) -> dict:
    """The fields every banner line renders, plus the section's own ``extra``."""
    return {
        "id": r["id"],
        "content": r.get("content", ""),
        "domain": r.get("domain", ""),
        **extra,
        "created_at": r.get("created_at"),
        "source_attribution": r.get("source_attribution", ""),
        "is_stale": bool(r.get("is_stale")),
    }


def _in_project(r: dict, project_root: str | None) -> bool:
    return memory_matches_project(
        r.get("directory_context"), bool(r.get("is_global")), project_root
    )


def _has_anchor_tag(r: dict) -> bool:
    """True when the row carries ``_anchor`` or an ``_anchor:`` tag."""
    tags = r.get("tags") or []
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except ValueError:
            tags = []
    return "_anchor" in tags or any(
        isinstance(t, str) and t.startswith("_anchor:") for t in tags
    )


def _fetch_anchors(store, project_root: str | None = None) -> list[dict]:
    """Fetch anchored memories (is_protected with _anchor tag) scoped to
    project_root or global (issue #604).

    The project predicate runs inside the query, before ORDER BY/LIMIT:
    pushed to the output it would let foreign-project rows outrank and
    starve the project's own anchors out of the LIMIT window (issue #604
    follow-up). The post-fetch ``memory_matches_project`` check stays as
    a defense-in-depth belt on top of the query's own suspenders.

    source: ADR-0498"""
    ancestors = project_ancestors(project_root)
    try:
        rows = store.call(session_anchor_rows, ancestors, int(_ANCHOR_LIMIT))
    except Exception as exc:  # noqa: BLE001 — hook boundary; failure is logged to the hook log, the banner degrades
        _log(f"anchor fetch failed (non-fatal): {exc}")
        return []
    return [
        _banner_entry(r, is_global=bool(r.get("is_global", False)))
        for r in rows
        if _in_project(r, project_root) and _has_anchor_tag(r)
    ]


def _fetch_team_decisions(
    store, exclude_ids: set, project_root: str | None = None
) -> list[dict]:
    """Fetch team decisions within the current project. source: ADR-1083"""
    try:
        rows = store.call(session_team_decision_rows, project_ancestors(project_root))
    except Exception as exc:  # noqa: BLE001 — hook boundary; failure is logged to the hook log, the banner degrades
        _log(f"team-decision fetch failed (non-fatal): {exc}")
        return []
    decisions = [
        _banner_entry(r, agent=r.get("agent_context", ""), heat=r.get("heat", 0.0))
        for r in rows
        if r["id"] not in exclude_ids
    ]
    return decisions[:3]  # Keep injection compact


def _fetch_hot_memories(
    store, exclude_ids: set, project_root: str | None = None
) -> list[dict]:
    """Fetch high-heat memories, excluding anchors, scoped to project_root
    or global (issue #604).

    Tier exclusion: auto-captured tool noise and block-replica snapshots
    must not appear in the session-start banner — they poison the injected
    context with raw "# Tool: Edit" captures.

    The project predicate runs inside the query, before ORDER BY/LIMIT:
    pushed to the output it would let foreign-project rows outrank and
    starve the project's own rows out of the LIMIT window (issue #604
    follow-up). The post-fetch ``memory_matches_project`` check stays as
    a defense-in-depth belt on top of the query's own suspenders.
    # contract: zetetic-team-subagents memory/contract.md §8b
    """
    try:
        rows = store.call(
            session_hot_rows,
            float(_MIN_HEAT),
            project_ancestors(project_root),
            int(_HOT_LIMIT + len(exclude_ids)),
        )
    except Exception as exc:  # noqa: BLE001 — hook boundary; failure is logged to the hook log, the banner degrades
        _log(f"hot-memory fetch failed (non-fatal): {exc}")
        return []
    hot = [
        _banner_entry(
            r,
            heat=r.get("heat", 0.0),
            is_global=bool(r.get("is_global", False)),
        )
        for r in rows
        if r["id"] not in exclude_ids and _in_project(r, project_root)
    ]
    return hot[:_HOT_LIMIT]
