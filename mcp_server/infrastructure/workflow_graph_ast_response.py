"""Normalizes AP ``query_graph`` responses into a flat list of dicts.

Split out of ``workflow_graph_source_ast.py`` (issue #275) — shared by
both the symbol-loading and edge-loading concerns, so it gets its own
narrow module rather than living inside either.

Infrastructure layer only. No core imports.
"""

from __future__ import annotations

import json
from typing import Any


def as_list(payload: Any) -> list[dict]:
    """Normalise AP's ``query_graph`` response into a list of dicts.

    AP's Stage-3a query_graph returns the shape:
        {"columns": ["a", "b"], "rows": [["1", "2"], ["3", "4"]], "status": "ok"}

    We zip ``columns`` with each row to produce ``[{"a": "1", "b": "2"}, ...]``.
    Error responses (``status: "error"``) surface as an empty list — the
    caller is already resilient to that case. Plain lists and dicts with a
    ``rows`` key containing dicts, or the older ``{"content"/"data": [...]}``
    shapes, are also accepted for forward-compat — see ``_from_legacy_shape``.
    """
    if payload is None:
        return []
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if not isinstance(payload, dict):
        return []
    if payload.get("status") == "error":
        return []
    cols, rows = payload.get("columns"), payload.get("rows")
    if isinstance(cols, list) and isinstance(rows, list):
        return _zip_columns_rows(cols, rows)
    return _from_legacy_shape(payload)


def _zip_columns_rows(cols: list, rows: list) -> list[dict]:
    """Zip a ``{columns, rows}`` pair into ``[{col: cell, ...}, ...]``.

    A row already shaped as a dict (some AP responses) passes through
    unchanged; a list row must match ``cols`` in length or it is dropped
    (a malformed row is not worth crashing the whole batch over).
    """
    out: list[dict] = []
    for row in rows:
        if isinstance(row, list) and len(row) == len(cols):
            out.append({str(c): row[i] for i, c in enumerate(cols)})
        elif isinstance(row, dict):
            out.append(row)
    return out


def _from_legacy_shape(payload: dict) -> list[dict]:
    """Older ``{"content": [...]}`` / ``{"data": [...]}`` response shapes:
    either a plain list of dict rows, or an MCP text-content wrapper whose
    ``text`` field is itself a JSON-encoded list of rows."""
    inner = payload.get("content") or payload.get("data")
    if not isinstance(inner, list):
        return []
    if inner and isinstance(inner[0], dict) and inner[0].get("type") == "text":
        try:
            parsed = json.loads(inner[0].get("text") or "")
            if isinstance(parsed, list):
                return [r for r in parsed if isinstance(r, dict)]
        except ValueError:
            return []
    return [r for r in inner if isinstance(r, dict)]


def build_path_tails(paths: list[str]) -> set[str]:
    """Expand each path into itself + every ``/``-boundary suffix ("tail").

    Shared by the symbol- and edge-loading queries (both need to match a
    ``paths`` entry, which may be absolute, against AP's repo-relative
    ``qualified_name``/``File.id`` prefixes — matching by tail lets either
    form work without knowing the other side's root).

    source: measured 2026-06-04 — a blanket ``LIMIT 500`` with no WHERE
    clause returned 0 rows for ``consolidate.py`` because the first 500
    Functions all started with ``benchmarks/*``/``_pipeline/*``; building
    every tail here lets the caller construct a server-side WHERE
    predicate that filters by file prefix instead of discarding in Python.
    """
    path_tails: set[str] = set()
    for p in paths:
        if not p:
            continue
        path_tails.add(p)
        parts = p.split("/")
        for i in range(1, len(parts)):
            path_tails.add("/".join(parts[i:]))
    return path_tails


__all__ = ["as_list", "build_path_tails"]
