"""Rows for HNSW index-path tests: a relevant row and distinct hidden rows.

The hidden rows are distinct jittered unit vectors around the query (cosine
about 0.96), all nearer the query than the relevant row (cosine 0.8), never
thousands of identical vectors, which degenerate the HNSW graph
(tests_py/_pg_hnsw.py).

source: ADR-1105
"""

from __future__ import annotations

import json
import math
import random
import uuid
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field

DIM = 384  # source: memory_config EMBEDDING_DIM (all-MiniLM-L6-v2)
# source: chosen so 1 - noise^2/2 (about 0.96) > 0.8, the relevant cosine.
_HIDDEN_NOISE = 0.3
# source: unit(q + 0.75 e) has cosine 1 / sqrt(1 + 0.75^2) = 0.8 with q.
_RELEVANT_OFFSET = 0.75
_SURVIVOR_AXIS = 380  # source: any axis orthogonal to the query and decoys


@dataclass
class Row:
    vector: list[float]
    content: str = field(default_factory=lambda: f"ann row {uuid.uuid4().hex}")
    heat: float = 0.5
    domain: str = ""
    is_stale: bool = False
    superseded: bool = False
    tags: list[str] = field(default_factory=list)
    created: str | None = None


def unit_axis(axis: int) -> list[float]:
    return [1.0 if i == axis else 0.0 for i in range(DIM)]


def _unit(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values]


def relevant_row(query: list[float], **kw) -> Row:
    """Cosine 0.8 with ``query``, created a month ago."""
    vector = [q + (_RELEVANT_OFFSET if i == 151 else 0.0) for i, q in enumerate(query)]
    month_ago = datetime.now(timezone.utc) - timedelta(days=30)
    kw.setdefault("created", month_ago.isoformat())
    return Row(_unit(vector), content=f"relevant {uuid.uuid4().hex}", **kw)


def hidden_near(query: list[float], count: int, **kw) -> list[Row]:
    rng = random.Random(1105)  # source: fixed seed, deterministic vectors
    sigma = _HIDDEN_NOISE / math.sqrt(DIM)
    return [
        Row(_unit([q + rng.gauss(0.0, sigma) for q in query]), **kw)
        for _ in range(count)
    ]


def _literal(values: list[float]) -> str:
    return "[" + ",".join(repr(v) for v in values) + "]"


_INSERT = (
    "INSERT INTO memories (content, embedding, tags, source, heat_base,"
    " no_decay, domain, is_stale, created_at)"
    " VALUES (%s, %s::vector, %s::jsonb, 'test', %s, TRUE, %s, %s,"
    " COALESCE(%s::timestamptz, NOW()))"
    " RETURNING id"
)


def insert_rows(store, rows: list[Row]) -> list[int]:
    """Insert ``rows``; superseded ones point at a far, live survivor."""
    with store.batch_pool.connection() as conn, conn.cursor() as cur:
        params = [
            (
                r.content,
                _literal(r.vector),
                json.dumps(r.tags),
                r.heat,
                r.domain,
                r.is_stale,
                r.created,
            )
            for r in rows
        ]
        cur.executemany(_INSERT, params, returning=True)
        ids = []
        while True:
            ids.append(cur.fetchone()["id"])
            if not cur.nextset():
                break
        superseded = [i for i, r in zip(ids, rows, strict=True) if r.superseded]
        if superseded:
            survivor_row = ("survivor", _literal(unit_axis(_SURVIVOR_AXIS)), "[]")
            cur.execute(_INSERT, (*survivor_row, 0.5, rows[0].domain, False, None))
            survivor = cur.fetchone()["id"]
            cur.execute(
                "UPDATE memories SET superseded_by_id = %s WHERE id = ANY(%s)",
                (survivor, superseded),
            )
        conn.execute("ANALYZE memories")
    return ids
