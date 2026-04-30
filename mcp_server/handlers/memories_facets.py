"""GET /api/memories/facets — aggregate counts so filter chips show
ALL options up-front rather than only what's been paged through.

Returns:
    {
      "total":      <int>,                # NOT is_stale memories
      "domains":    [{"name": str, "count": int}, ...],   # sorted desc
      "stages":     {"labile": int, "early_ltp": int, ...},
      "emotions":   {"urgent": int, "positive": int, "negative": int, "neutral": int},
      "global":     <int>,
      "protected":  <int>,
      "hot":        <int>                  # heat_base >= 0.5
    }

Three SQL queries total, each indexed; ~5-50 ms even at 1M memories.
"""

from __future__ import annotations

import json


def _send_json(handler, status: int, payload: dict) -> None:
    body = json.dumps(payload, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "max-age=10")
    handler.end_headers()
    try:
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass


def serve(handler, store) -> None:
    try:
        # Q1: per-domain counts (sorted desc).
        cur = store._execute(
            "SELECT COALESCE(NULLIF(domain, ''), '__unknown__') AS dom, "
            "COUNT(*) AS c "
            "FROM memories WHERE NOT is_stale "
            "GROUP BY dom ORDER BY c DESC LIMIT 200"
        )
        domain_rows = cur.fetchall()

        # Q2: per-stage + global + protected + hot + total in one pass.
        cur = store._execute(
            "SELECT "
            "  COUNT(*) AS total, "
            "  COUNT(*) FILTER (WHERE consolidation_stage = 'labile')          AS s_labile, "
            "  COUNT(*) FILTER (WHERE consolidation_stage = 'early_ltp')       AS s_early, "
            "  COUNT(*) FILTER (WHERE consolidation_stage = 'late_ltp')        AS s_late, "
            "  COUNT(*) FILTER (WHERE consolidation_stage = 'consolidated')    AS s_cons, "
            "  COUNT(*) FILTER (WHERE consolidation_stage = 'reconsolidating') AS s_recon, "
            "  COUNT(*) FILTER (WHERE is_global = TRUE)     AS n_global, "
            "  COUNT(*) FILTER (WHERE is_protected = TRUE)  AS n_protected, "
            "  COUNT(*) FILTER (WHERE heat_base >= 0.5)     AS n_hot, "
            "  COUNT(*) FILTER (WHERE importance >= 0.75)                                                  AS e_urgent, "
            "  COUNT(*) FILTER (WHERE emotional_valence >= 0.25 AND importance < 0.75)                     AS e_pos, "
            "  COUNT(*) FILTER (WHERE emotional_valence <= -0.25 AND importance < 0.75)                    AS e_neg, "
            "  COUNT(*) FILTER (WHERE emotional_valence > -0.25 AND emotional_valence < 0.25 AND importance < 0.75) AS e_neutral "
            "FROM memories WHERE NOT is_stale"
        )
        agg = cur.fetchone()
        agg = dict(agg) if not isinstance(agg, dict) else agg

        domains = [
            {
                "name": dict(r)["dom"] if not isinstance(r, dict) else r["dom"],
                "count": int(dict(r)["c"] if not isinstance(r, dict) else r["c"]),
            }
            for r in domain_rows
        ]

        payload = {
            "total": int(agg.get("total") or 0),
            "domains": domains,
            "stages": {
                "labile": int(agg.get("s_labile") or 0),
                "early_ltp": int(agg.get("s_early") or 0),
                "late_ltp": int(agg.get("s_late") or 0),
                "consolidated": int(agg.get("s_cons") or 0),
                "reconsolidating": int(agg.get("s_recon") or 0),
            },
            "emotions": {
                "urgent": int(agg.get("e_urgent") or 0),
                "positive": int(agg.get("e_pos") or 0),
                "negative": int(agg.get("e_neg") or 0),
                "neutral": int(agg.get("e_neutral") or 0),
            },
            "global": int(agg.get("n_global") or 0),
            "protected": int(agg.get("n_protected") or 0),
            "hot": int(agg.get("n_hot") or 0),
        }
        _send_json(handler, 200, payload)
    except Exception as exc:
        _send_json(
            handler,
            500,
            {
                "status": "error",
                "reason": "facets_query_failed",
                "detail": f"{type(exc).__name__}: {exc}",
            },
        )
