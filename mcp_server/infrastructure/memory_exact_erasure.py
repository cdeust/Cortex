"""Locate retained byte-identical supersession copies for hard forget (#707).

Scope equality alone does not authorize erasing an independent memory. Only
copies connected to the requested row by supersession edges are included.
source: ADR-1111; PR #827 security review 6470052457.
"""

from __future__ import annotations

from typing import Any, cast, TYPE_CHECKING

from mcp_server.infrastructure.memory_exact_sql import bypass, params, predicate

if TYPE_CHECKING:
    from typing_extensions import LiteralString
    from mcp_server.infrastructure.memory_erasure import ErasureReport


def retained_copy_rows(conn: Any, memory_id: int, sqlite: bool) -> list[dict]:
    query = "SELECT * FROM memories WHERE id = %s"
    if not sqlite:
        query += " FOR UPDATE NOWAIT"
    row = conn.execute(cast("LiteralString", query), (memory_id,)).fetchone()
    if row is None:
        return []
    data = dict(row)
    if bypass(data):
        return [data]
    query = "SELECT * FROM memories WHERE " + predicate(sqlite, live=False)  # noqa: S608 -- fixed schema predicate; values are bound
    if not sqlite:
        query += " FOR UPDATE NOWAIT"
    rows = [
        dict(item)
        for item in conn.execute(
            cast("LiteralString", query), params(data, sqlite)
        ).fetchall()
    ]
    return _connected_rows(rows, memory_id)


def _connected_rows(rows: list[dict], memory_id: int) -> list[dict]:
    by_id = {row["id"]: row for row in rows}
    neighbors = {row_id: set() for row_id in by_id}
    for row in rows:
        for field in ("supersedes_id", "superseded_by_id"):
            linked = row[field]
            if linked in by_id:
                neighbors[row["id"]].add(linked)
                neighbors[linked].add(row["id"])
    selected, visited, pending = [], set(), [memory_id]
    # Every vertex is processed once, and only finite stored edges are followed.
    while pending:
        current = pending.pop()
        if current in visited or current not in by_id:
            continue
        visited.add(current)
        selected.append(by_id[current])
        pending.extend(neighbors[current] - visited)
    return selected


def merge_erasure_report(target: ErasureReport, copy: ErasureReport) -> None:
    target.deleted = target.deleted or copy.deleted
    target.page_paths.extend(copy.page_paths)
    for key, count in copy.counts.items():
        target.counts[key] = target.counts.get(key, 0) + count
