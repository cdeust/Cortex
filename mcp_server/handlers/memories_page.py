"""GET /api/memories — keyset-paged memory listing for Knowledge + Board tabs.

Replaces the in-memory ``JUG.state.lastData.nodes.filter(type==='memory')``
pattern that breaks at high N. Pagination is keyset over ``(sort_key, id)``
pairs so it scales linearly with N regardless of how many memories exist.

Query params:
    cursor   base64-encoded JSON {sort_key, id}; omit for first page
    limit    int, default 50, capped at 200
    domain   exact-match filter on memories.domain (optional)
    stage    consolidation_stage filter (labile/early_ltp/late_ltp/
             consolidated/reconsolidating)
    sort     'heat' | 'recent' | 'oldest' — defaults to 'heat'
    search   plainto_tsquery FTS over content_tsv (optional)
    include_global  '1' includes global memories regardless of domain

Response:
    {
      "items": [ {memory dict matching workflow_graph.v1 memory node shape}, ...],
      "next_cursor": "<base64>" | null,
      "page_count": <int>,
      "sort": <str>
    }

The cursor is opaque to the client; pass whatever the previous page
returned. ``next_cursor === null`` means the last page has been served.
"""

from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import parse_qs, urlsplit


_SORT_ORDER_BY = {
    # heat_base is the persisted base heat; effective_heat is a function
    # call that we skip here for listing speed.
    "heat": "heat_base DESC, id DESC",
    "recent": "created_at DESC, id DESC",
    "oldest": "created_at ASC,  id ASC",
}
_SORT_KEY_COLUMN = {
    "heat": "heat_base",
    "recent": "created_at",
    "oldest": "created_at",
}
_SORT_DIRECTION = {
    "heat": "<",  # next page has smaller heat or same heat with smaller id
    "recent": "<",
    "oldest": ">",
}
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


def _decode_cursor(s: str | None) -> dict | None:
    if not s:
        return None
    try:
        raw = base64.urlsafe_b64decode(s.encode("utf-8") + b"==").decode("utf-8")
        return json.loads(raw)
    except Exception:
        return None


def _encode_cursor(payload: dict) -> str:
    raw = json.dumps(payload, default=str).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _send_json(handler, status: int, payload: dict) -> None:
    body = json.dumps(payload, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()
    try:
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass


def _row_to_node(row: Any) -> dict:
    """Shape a memory row to match the workflow_graph.v1 memory-node fields
    that knowledge.js + timeline.js read directly. Missing fields are
    populated with safe defaults."""
    d = dict(row) if not isinstance(row, dict) else row
    # Map emotional_valence to a discrete emotion bucket the UI knows.
    val = d.get("emotional_valence") or 0.0
    emotion = None
    if val >= 0.55:
        emotion = "satisfaction"
    elif val >= 0.25:
        emotion = "discovery"
    elif val <= -0.55:
        emotion = "frustration"
    elif val <= -0.25:
        emotion = "confusion"
    if d.get("importance") and d["importance"] >= 0.75:
        emotion = "urgency"
    return {
        "id": "memory:" + str(d.get("id")),
        "memory_id": d.get("id"),
        "type": "memory",
        "kind": "memory",
        "label": d.get("content") or "",
        "content": d.get("content") or "",
        "domain": d.get("domain") or "",
        "domain_id": "domain:" + (d.get("domain") or "__global__"),
        "tags": d.get("tags") or [],
        "heat": float(d.get("heat_base") or 0.0),
        "importance": float(d.get("importance") or 0.0),
        "stage": d.get("consolidation_stage") or "labile",
        "consolidationStage": d.get("consolidation_stage") or "labile",
        "consolidation_stage": d.get("consolidation_stage") or "labile",
        "createdAt": d.get("created_at"),
        "lastAccessed": d.get("last_accessed"),
        "isProtected": bool(d.get("is_protected")),
        "is_protected": bool(d.get("is_protected")),
        "isGlobal": bool(d.get("is_global")),
        "is_global": bool(d.get("is_global")),
        "emotion": emotion,
        "emotional_valence": float(val) if val is not None else 0.0,
        "store_type": d.get("store_type") or "episodic",
        "access_count": int(d.get("access_count") or 0),
        "useful_count": int(d.get("useful_count") or 0),
    }


def _build_query(
    sort: str,
    has_cursor: bool,
    has_domain: bool,
    has_stage: bool,
    has_search: bool,
    has_min_heat: bool,
    has_emotion: bool,
    protected_only: bool,
    global_only: bool,
    include_global: bool,
) -> str:
    where: list[str] = ["NOT is_stale"]
    if has_cursor:
        col = _SORT_KEY_COLUMN[sort]
        op = _SORT_DIRECTION[sort]
        where.append(f"({col}, id) {op} (%s, %s)")
    if global_only:
        where.append("is_global = TRUE")
    elif has_domain:
        if include_global:
            where.append("(domain = %s OR is_global = TRUE)")
        else:
            where.append("domain = %s")
    if has_stage:
        where.append("consolidation_stage = %s")
    if has_search:
        where.append("content_tsv @@ plainto_tsquery('english', %s)")
    if has_min_heat:
        where.append("heat_base >= %s")
    if has_emotion:
        # emotion is bucketed from emotional_valence; map at the SQL level.
        # Buckets: 'positive' (>=0.25), 'negative' (<=-0.25), 'urgent'
        # (importance >= 0.75), 'neutral' (everything else).
        # We pass the bucket as a placeholder and let the WHERE clause
        # below dispatch via CASE-equivalent boolean.
        where.append(
            "(("
            "  %s = 'urgent' AND importance >= 0.75"
            ") OR ("
            "  %s = 'positive' AND emotional_valence >= 0.25 AND importance < 0.75"
            ") OR ("
            "  %s = 'negative' AND emotional_valence <= -0.25 AND importance < 0.75"
            ") OR ("
            "  %s = 'neutral' AND emotional_valence > -0.25 AND emotional_valence < 0.25 AND importance < 0.75"
            "))"
        )
    if protected_only:
        where.append("is_protected = TRUE")
    return (
        "SELECT id, content, domain, heat_base, importance, "
        "consolidation_stage, emotional_valence, tags, created_at, "
        "last_accessed, is_protected, is_global, store_type, "
        "access_count, useful_count "
        "FROM memories "
        "WHERE " + " AND ".join(where) + " "
        f"ORDER BY {_SORT_ORDER_BY[sort]} "
        "LIMIT %s"
    )


def serve(handler, store) -> None:
    qs = parse_qs(urlsplit(handler.path).query)

    sort = (qs.get("sort", ["heat"])[0] or "heat").strip()
    if sort not in _SORT_ORDER_BY:
        sort = "heat"

    try:
        limit = int(qs.get("limit", [str(_DEFAULT_LIMIT)])[0])
    except (TypeError, ValueError):
        limit = _DEFAULT_LIMIT
    limit = max(1, min(_MAX_LIMIT, limit))

    cursor = _decode_cursor(qs.get("cursor", [None])[0])
    domain = (qs.get("domain", [None])[0] or "").strip() or None
    stage = (qs.get("stage", [None])[0] or "").strip() or None
    search = (qs.get("search", [None])[0] or "").strip() or None
    emotion = (qs.get("emotion", [None])[0] or "").strip() or None
    if emotion not in ("urgent", "positive", "negative", "neutral", None):
        emotion = None
    try:
        min_heat = (
            float(qs.get("min_heat", [""])[0]) if qs.get("min_heat", [""])[0] else None
        )
    except (TypeError, ValueError):
        min_heat = None
    protected_only = qs.get("protected", ["0"])[0] in ("1", "true", "yes")
    global_only = qs.get("global", ["0"])[0] in ("1", "true", "yes")
    include_global = qs.get("include_global", ["1"])[0] in ("1", "true", "yes")

    sql = _build_query(
        sort=sort,
        has_cursor=cursor is not None,
        has_domain=domain is not None,
        has_stage=stage is not None,
        has_search=search is not None,
        has_min_heat=min_heat is not None,
        has_emotion=emotion is not None,
        protected_only=protected_only,
        global_only=global_only,
        include_global=include_global,
    )
    params: list = []
    if cursor is not None:
        params.extend([cursor.get("k"), cursor.get("id")])
    if not global_only and domain is not None:
        params.append(domain)
    if stage is not None:
        params.append(stage)
    if search is not None:
        params.append(search)
    if min_heat is not None:
        params.append(min_heat)
    if emotion is not None:
        # Four placeholders for the four-bucket CASE-style WHERE clause.
        params.extend([emotion, emotion, emotion, emotion])
    # Over-fetch by 1 so we can detect "more pages exist" without a count.
    params.append(limit + 1)

    try:
        cur = store._execute(sql, tuple(params))
        rows = cur.fetchall()
    except Exception as exc:
        _send_json(
            handler,
            500,
            {
                "status": "error",
                "reason": "query_failed",
                "detail": f"{type(exc).__name__}: {exc}",
            },
        )
        return

    has_more = len(rows) > limit
    items = list(rows[:limit])

    next_cursor: str | None = None
    if has_more and items:
        last = dict(items[-1]) if not isinstance(items[-1], dict) else items[-1]
        sort_value: Any
        if sort == "heat":
            sort_value = (
                float(last["heat_base"]) if last.get("heat_base") is not None else 0.0
            )
        else:
            ts = last.get("created_at")
            sort_value = ts.isoformat() if hasattr(ts, "isoformat") else ts
        next_cursor = _encode_cursor({"k": sort_value, "id": last["id"]})

    nodes = [_row_to_node(r) for r in items]
    _send_json(
        handler,
        200,
        {
            "items": nodes,
            "next_cursor": next_cursor,
            "page_count": len(nodes),
            "sort": sort,
        },
    )
