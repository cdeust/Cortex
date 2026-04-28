"""PostgreSQL persistence for precomputed graph-layout coordinates.

Reads / writes ``workflow_graph_layout`` (defined in pg_schema.py).
Pure infrastructure — no core imports. The handler layer composes this
with ``core.layout_engine`` to produce + persist coords.
"""

from __future__ import annotations

import time
from typing import Iterable


def _conn(store):
    """Context-manager accessor on ``PgMemoryStore``.

    The PG store exposes a ``batch_pool`` (psycopg_pool ConnectionPool)
    via the property declared in pg_store.py. We use the batch pool —
    layout reads/writes are bulk, not interactive — and isolate the
    pool name here so the rest of this module never touches psycopg
    directly.

    Raises:
        AttributeError: when called on a SQLite-backed store. Layout
            persistence is PG-only by design (the BIGINT column type,
            TIMESTAMPTZ default, and bulk executemany pattern all
            assume PG).
    """
    pool = getattr(store, "batch_pool", None)
    if pool is None:
        raise AttributeError(
            "layout_pg_store requires PgMemoryStore (no .batch_pool on this store)"
        )
    return pool.connection()


def write_layout(
    store,
    coords: Iterable[tuple[str, float, float]],
    kinds: dict[str, str],
    *,
    topology_fingerprint: str,
) -> int:
    """Persist ``(node_id, x, y, kind)`` rows. Returns layout_version.

    ``layout_version`` is monotonically increasing wall-clock-millis;
    we use it as the cache key the tile + quadtree endpoints invalidate
    on. Bulk-inserted via ``executemany`` for speed (well under 1s for
    1M rows on local PG).

    The write is fully replacing — every prior row is removed before
    the new set lands. This is correct because the layout is a global
    snapshot, not an incremental update.
    """
    layout_version = int(time.time() * 1000)
    rows = [
        (
            nid,
            float(x),
            float(y),
            kinds.get(nid, "unknown"),
            topology_fingerprint,
            layout_version,
        )
        for nid, x, y in coords
    ]
    if not rows:
        return layout_version
    sql_clear = "DELETE FROM workflow_graph_layout"
    sql_ins = (
        "INSERT INTO workflow_graph_layout "
        "(node_id, x, y, kind, topology_fingerprint, layout_version) "
        "VALUES (%s, %s, %s, %s, %s, %s)"
    )
    with _conn(store) as conn, conn.cursor() as cur:
        cur.execute(sql_clear)
        cur.executemany(sql_ins, rows)
        conn.commit()
    return layout_version


def read_layout_version(store) -> dict | None:
    """Return ``{'version', 'fingerprint', 'count'}`` or None if empty."""
    sql = (
        "SELECT layout_version, topology_fingerprint, COUNT(*) "
        "FROM workflow_graph_layout "
        "GROUP BY layout_version, topology_fingerprint "
        "ORDER BY layout_version DESC LIMIT 1"
    )
    with _conn(store) as conn, conn.cursor() as cur:
        cur.execute(sql)
        row = cur.fetchone()
    if not row:
        return None
    return {"version": int(row[0]), "fingerprint": row[1], "count": int(row[2])}


def read_all_positions(store) -> list[tuple[str, float, float, str]]:
    """Return every persisted ``(node_id, x, y, kind)`` row.

    Used by the quadtree endpoint to ship the full picking index to
    the client. At 1M nodes the result is ~30 MB unencoded; the
    quadtree endpoint dict-encodes ``id`` + ``kind`` and gzips the
    Arrow IPC frame to ~7 MB.
    """
    sql = "SELECT node_id, x, y, kind FROM workflow_graph_layout"
    with _conn(store) as conn, conn.cursor() as cur:
        cur.execute(sql)
        return [(r[0], float(r[1]), float(r[2]), r[3]) for r in cur.fetchall()]


def read_positions_in_bbox(
    store,
    *,
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
) -> list[tuple[str, float, float, str]]:
    """Return positions intersecting the world-space bbox.

    Used by the tile renderer: each tile request asks PG for only the
    nodes whose coordinates fall inside the tile's world-space cell.
    The B-tree on (x, y) (see ``INDEXES_DDL`` in pg_schema.py) keeps
    this query under 5 ms even for 10M-row tables.
    """
    sql = (
        "SELECT node_id, x, y, kind FROM workflow_graph_layout "
        "WHERE x BETWEEN %s AND %s AND y BETWEEN %s AND %s"
    )
    with _conn(store) as conn, conn.cursor() as cur:
        cur.execute(sql, (min_x, max_x, min_y, max_y))
        return [(r[0], float(r[1]), float(r[2]), r[3]) for r in cur.fetchall()]
