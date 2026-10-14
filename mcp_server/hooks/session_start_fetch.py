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
from mcp_server.shared.project_scope import memory_matches_project, project_ancestors


# source: ADR-0498
_ANCHORS_SQL = (
    "SELECT m.id, m.content, m.tags, m.domain, m.is_global, "
    "m.directory_context, "
    "m.created_at, m.source_attribution, m.is_stale "
    # source: ADR-0498
    "FROM memories m JOIN current_memories cm ON cm.id = m.id "
    "WHERE m.is_protected = TRUE "
    # Exclude auto-captured noise (defense-in-depth — they should never
    # be protected, but guard against misconfiguration).
    # contract: zetetic-team-subagents memory/contract.md §8b
    "AND NOT (m.tags @> '[\"auto-captured\"]'::jsonb) "
    # source: ADR-0498
    "AND m.superseded_by_id IS NULL "
    "AND (m.is_global = TRUE OR m.directory_context = ANY(%s::TEXT[])) "
    "ORDER BY effective_heat(m, NOW()) DESC LIMIT %s"
)

# source: ADR-0498
_TEAM_DECISIONS_SQL = (
    "SELECT m.id, m.content, m.domain, m.agent_context, "
    "m.created_at, m.source_attribution, m.is_stale, "
    # JOIN current_memories: same pattern as _fetch_anchors —
    # supersession exclusion via the view, m stays table-typed
    # for effective_heat().
    "effective_heat(m, NOW()) AS heat "
    "FROM memories m JOIN current_memories cm ON cm.id = m.id "
    "WHERE m.is_team_decision = TRUE AND NOT m.is_benchmark "
    "AND (m.is_global = TRUE OR m.directory_context = ANY(%s::TEXT[])) "
    "AND m.agent_context != '' "
    # source: ADR-0498
    "AND m.superseded_by_id IS NULL "
    "ORDER BY effective_heat(m, NOW()) DESC LIMIT 5"
)

# contract: zetetic-team-subagents memory/contract.md §8b
_HOT_SQL = (
    "SELECT id, content, domain, heat_base AS heat, tags, is_global, "
    "directory_context, "
    "created_at, source_attribution, is_stale "
    # current_memories: hot-pool content injected into the session
    # banner — supersession chain heads only.
    "FROM current_memories "
    "WHERE heat_base >= %s "
    # Exclude tier-1 noise: auto-captured tool outputs and block replicas.
    # JSONB containment: tags @> '[\"x\"]' is true when the array contains x.
    # contract: zetetic-team-subagents memory/contract.md §8b
    "AND NOT (tags @> '[\"auto-captured\"]'::jsonb "
    "         OR tags @> '[\"memory-replica\"]'::jsonb) "
    # source: ADR-0498
    "AND superseded_by_id IS NULL "
    "AND (is_global = TRUE OR directory_context = ANY(%s::TEXT[])) "
    "ORDER BY heat_base DESC LIMIT %s"
)


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


def _fetch_anchors(conn, project_root: str | None = None) -> list[dict]:
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
        rows = conn.execute(_ANCHORS_SQL, (ancestors, int(_ANCHOR_LIMIT))).fetchall()
    except Exception as exc:  # noqa: BLE001 — hook boundary; failure is logged to the hook log, the banner degrades
        _log(f"anchor fetch failed (non-fatal): {exc}")
        return []
    return [
        _banner_entry(r, is_global=bool(r.get("is_global", False)))
        for r in rows
        if _in_project(r, project_root) and _has_anchor_tag(r)
    ]


def _fetch_team_decisions(
    conn, exclude_ids: set, project_root: str | None = None
) -> list[dict]:
    """Fetch team decisions within the current project. source: ADR-1083"""
    try:
        rows = conn.execute(
            _TEAM_DECISIONS_SQL, (project_ancestors(project_root),)
        ).fetchall()
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
    conn, exclude_ids: set, project_root: str | None = None
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
    params = (
        float(_MIN_HEAT),
        project_ancestors(project_root),
        int(_HOT_LIMIT + len(exclude_ids)),
    )
    try:
        rows = conn.execute(_HOT_SQL, params).fetchall()
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
