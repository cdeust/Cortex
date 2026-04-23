"""Non-wiki endpoint helpers for the standalone HTTP server.

Owns:

* ``serve_sankey`` — /api/sankey dashboard query
* ``serve_graph`` / ``serve_discussions`` / ``serve_discussion_detail``
* ``serve_static`` — sandboxed static-file reader for ``/js/`` + ``/css/``
* ``serve_file_diff`` — thin delegate to ``http_file_diff``

All response shaping flows through ``http_standalone_response`` so the
HTTP boilerplate lives in one place.
"""

from __future__ import annotations

import re
from pathlib import Path

from mcp_server.server.http_standalone_graph import (
    build_discussion_detail,
    build_discussions_response,
    get_graph_response,
)
from mcp_server.server.http_standalone_response import (
    send_json_error,
    send_json_ok,
    send_plain_error,
)

_STAGES = (
    "labile",
    "early_ltp",
    "late_ltp",
    "consolidated",
    "reconsolidating",
)

_STAGE_METRICS_SQL = (
    "SELECT COUNT(*) as count, "
    "AVG(heat) as avg_heat, AVG(importance) as avg_importance, "
    "AVG(replay_count) as avg_replay, AVG(access_count) as avg_access, "
    "AVG(encoding_strength) as avg_encoding, "
    "AVG(interference_score) as avg_interference, "
    "AVG(schema_match_score) as avg_schema, "
    "AVG(hippocampal_dependency) as avg_hippo, "
    "AVG(plasticity) as avg_plasticity, "
    "AVG(stability) as avg_stability, "
    "AVG(hours_in_stage) as avg_hours "
    "FROM memories WHERE consolidation_stage = %s "
    "AND NOT is_benchmark AND NOT is_stale"
)


def _sankey_transitions(store) -> list[dict]:
    rows = store._conn.execute(
        "SELECT from_stage, to_stage, COUNT(*) as count "
        "FROM stage_transitions "
        "GROUP BY from_stage, to_stage "
        "ORDER BY from_stage, to_stage"
    ).fetchall()
    return [dict(r) for r in rows]


def _sankey_timing(store) -> dict[str, dict[str, float]]:
    rows = store._conn.execute(
        "SELECT from_stage, to_stage, "
        "AVG(hours_in_prev_stage) as avg_hours, "
        "MIN(hours_in_prev_stage) as min_hours, "
        "MAX(hours_in_prev_stage) as max_hours "
        "FROM stage_transitions GROUP BY from_stage, to_stage"
    ).fetchall()
    timing: dict[str, dict[str, float]] = {}
    for r in rows:
        key = r["from_stage"] + "->" + r["to_stage"]
        timing[key] = {
            "avg_hours": round(r["avg_hours"], 1),
            "min_hours": round(r["min_hours"], 1),
            "max_hours": round(r["max_hours"], 1),
        }
    return timing


def _sankey_stage_metrics(store) -> dict[str, dict]:
    stage_metrics: dict[str, dict] = {}
    for s in _STAGES:
        r = store._conn.execute(_STAGE_METRICS_SQL, (s,)).fetchone()
        stage_metrics[s] = {
            k: round(v, 3) if isinstance(v, float) else (v or 0)
            for k, v in dict(r).items()
        }
    return stage_metrics


def serve_sankey(handler, store) -> None:
    """GET /api/sankey — consolidation-pipeline Sankey dataset."""
    try:
        total = store._conn.execute(
            "SELECT COUNT(*) as c FROM memories WHERE NOT is_benchmark AND NOT is_stale"
        ).fetchone()
        send_json_ok(
            handler,
            {
                "transitions": _sankey_transitions(store),
                "timing": _sankey_timing(store),
                "stage_metrics": _sankey_stage_metrics(store),
                "total_memories": total["c"],
            },
        )
    except Exception as e:
        send_json_error(handler, e)


def serve_graph(handler, store) -> None:
    """GET /api/graph — cached workflow graph or warming placeholder."""
    try:
        send_json_ok(handler, get_graph_response(store, handler.path))
    except Exception as e:
        send_json_error(handler, e)


def serve_graph_progress(handler) -> None:
    """GET /api/graph/progress — background-build progress snapshot."""
    from mcp_server.server.http_standalone_graph import get_build_progress

    try:
        send_json_ok(handler, get_build_progress())
    except Exception as e:
        send_json_error(handler, e)


def serve_graph_phase(handler) -> None:
    """GET /api/graph/phase?name=<L0|L1|…|L6:proj|L6_CROSS>

    Returns only the nodes + edges produced by that phase plus its
    ``ready`` flag and dependency list. The client appends the
    payload to its live scene when ``ready=true``; until then the
    client skips it (guarantees it never appends an edge whose
    endpoint is in a later phase).

    Per-project keys contain a colon (``L6:Cortex``) — the browser
    url-encodes that as ``L6%3ACortex``, so we MUST percent-decode
    before lookup or every L6:<proj> fetch returns an empty payload.
    """
    from urllib.parse import unquote

    from mcp_server.server.http_standalone_graph import get_phase_payload

    try:
        name = ""
        if "?" in handler.path:
            for p in handler.path.split("?", 1)[1].split("&"):
                if p.startswith("name="):
                    name = unquote(p[5:])
        send_json_ok(handler, get_phase_payload(name))
    except Exception as e:
        send_json_error(handler, e)


def serve_discussions(handler) -> None:
    """GET /api/discussions — paginated session list."""
    try:
        send_json_ok(handler, build_discussions_response(handler.path))
    except Exception as e:
        send_json_error(handler, e)


def serve_discussion_detail(handler, path_no_qs: str) -> None:
    """GET /api/discussion/<session_id> — single-session transcript."""
    try:
        session_id = path_no_qs.rsplit("/", 1)[-1]
        send_json_ok(handler, build_discussion_detail(session_id))
    except Exception as e:
        send_json_error(handler, e)


def serve_static(handler, base_dir: Path, filename: str, content_type: str) -> None:
    """Sandboxed read-only static-file reader for ``/js/`` and ``/css/``.

    Security: strip directory components, reject hidden files / null
    bytes / non-alphanumeric names, match against a directory-listing
    whitelist so the user-supplied path never drives the filesystem
    read.
    """
    safe_name = Path(filename).name
    if (
        not safe_name
        or safe_name.startswith(".")
        or "\x00" in safe_name
        or not re.match(r"^[\w][\w.\-]*$", safe_name)
    ):
        send_plain_error(handler, 403)
        return
    resolved_base = base_dir.resolve()
    actual_files = {f.name: f for f in resolved_base.iterdir() if f.is_file()}
    if safe_name not in actual_files:
        send_plain_error(handler, 404)
        return
    body = actual_files[safe_name].read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", content_type + "; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()
    handler.wfile.write(body)


def serve_file_diff(handler) -> None:
    """Thin delegate to ``http_file_diff.serve_file_diff``."""
    from mcp_server.server.http_file_diff import serve_file_diff as _serve

    _serve(handler)


# ``build_methodology_handler`` removed in Gap 10 — it imported a
# symbol (``build_methodology_graph``) that never existed in
# ``graph_builder.py``, so ``http_standalone --type methodology`` was
# broken-on-start. The MCP tool ``get_methodology_graph`` now covers
# the same use case without a separate HTTP surface.
