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
        {
          "columns": ["a", "b"],
          "rows":    [["1", "2"], ["3", "4"]],
          "status":  "ok",
          ...
        }

    We zip ``columns`` with each row to produce ``[{"a": "1", "b": "2"}, ...]``.
    Error responses (``status: "error"``) surface as an empty list — the
    caller is already resilient to that case. Plain lists and dicts with a
    ``rows`` key containing dicts are also accepted for forward-compat.
    """
    if payload is None:
        return []
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if not isinstance(payload, dict):
        return []
    if payload.get("status") == "error":
        return []
    cols = payload.get("columns")
    rows = payload.get("rows")
    if isinstance(cols, list) and isinstance(rows, list):
        out: list[dict] = []
        for row in rows:
            if isinstance(row, list) and len(row) == len(cols):
                out.append({str(c): row[i] for i, c in enumerate(cols)})
            elif isinstance(row, dict):
                out.append(row)
        return out
    # Older ``{"content": [...]}`` / ``{"data": [...]}`` shapes.
    inner = payload.get("content") or payload.get("data")
    if isinstance(inner, list):
        if inner and isinstance(inner[0], dict) and inner[0].get("type") == "text":
            try:
                parsed = json.loads(inner[0].get("text") or "")
                if isinstance(parsed, list):
                    return [r for r in parsed if isinstance(r, dict)]
            except ValueError:
                return []
        return [r for r in inner if isinstance(r, dict)]
    return []


__all__ = ["as_list"]
