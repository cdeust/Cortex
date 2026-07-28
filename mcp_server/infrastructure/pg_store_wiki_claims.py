"""wiki.claim_events DB operations.

Split out of ``pg_store_wiki.py`` (originally 890 lines, over the
300-line file limit — CLAUDE.md "Code Quality Rules") purely for size
compliance; no logic changed.

Pure infrastructure — no core imports, no handler imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from psycopg import Connection

import json


from mcp_server.infrastructure.pg_store_wiki_common import _returning_id


def insert_claim_events(conn: Connection, claims: list[dict]) -> list[int]:
    """Bulk insert ClaimEvent rows. Returns the new ids in order.

    Each ``claims`` dict requires: ``text``, ``claim_type``. Optional:
    memory_id, session_id, entity_ids, evidence_refs, confidence,
    supersedes, embedding (vector or None).

    All inserted in one cursor cycle for throughput.
    """
    if not claims:
        return []

    sql = """
    INSERT INTO wiki.claim_events (
        memory_id, session_id, text, claim_type, entity_ids,
        evidence_refs, confidence, supersedes
    ) VALUES (
        %(memory_id)s, %(session_id)s, %(text)s, %(claim_type)s,
        %(entity_ids)s, %(evidence_refs)s::jsonb, %(confidence)s,
        %(supersedes)s
    ) RETURNING id;
    """
    out: list[int] = []
    with conn.cursor() as cur:
        for c in claims:
            params = {
                "memory_id": c.get("memory_id"),
                "session_id": c.get("session_id", ""),
                "text": c["text"][:1900],
                "claim_type": c.get("claim_type", "assertion"),
                "entity_ids": c.get("entity_ids", []),
                "evidence_refs": json.dumps(c.get("evidence_refs", [])),
                "confidence": c.get("confidence", 0.5),
                "supersedes": c.get("supersedes"),
            }
            cur.execute(sql, params)
            out.append(_returning_id(cur.fetchone()))
    return out


def delete_claims_for_memory(conn: Connection, memory_id: int) -> int:
    """Remove all claim_events derived from a single memory.

    Used before re-extraction to keep the table clean of stale claims.
    """
    with conn.cursor() as cur:
        cur.execute("DELETE FROM wiki.claim_events WHERE memory_id = %s", (memory_id,))
        return cur.rowcount


def get_claims_for_memory(conn: Connection, memory_id: int) -> list[dict]:
    """Return all claim_events derived from a single memory."""
    from psycopg.rows import dict_row  # noqa: PLC0415 — optional dependency ([postgresql] extra); imported where used so environments without it keep working

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM wiki.claim_events WHERE memory_id = %s ORDER BY id",
            (memory_id,),
        )
        return list(cur.fetchall())


def get_entities_by_memory(
    conn: Connection, memory_ids: list[int]
) -> dict[int, list[int]]:
    """Pre-fetch memory_id → list[entity_id] for a batch of memories."""
    if not memory_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT memory_id, entity_id FROM memory_entities "
            "WHERE memory_id = ANY(%s)",
            (list(memory_ids),),
        )
        rows = cur.fetchall()
    out: dict[int, list[int]] = {}
    for r in rows:
        if isinstance(r, dict):
            mid, eid = r["memory_id"], r["entity_id"]
        else:
            mid, eid = r[0], r[1]
        out.setdefault(mid, []).append(eid)
    return out


# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_MIN_ENTITY_NAME_CHARS = 3


def get_entity_name_index(conn: Connection, limit: int = 5000) -> dict[str, int]:
    """Return name → entity_id map for inline-mention matching.

    Limit caps the index size for in-memory matching against claim text.
    Heat-ranked so the most frequently-touched entities win.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT name, id FROM entities ORDER BY heat DESC NULLS LAST LIMIT %s",
            (limit,),
        )
        rows = cur.fetchall()
    out: dict[str, int] = {}
    for r in rows:
        if isinstance(r, dict):
            name, eid = r["name"], r["id"]
        else:
            name, eid = r[0], r[1]
        if name and len(name) >= _MIN_ENTITY_NAME_CHARS:
            out[name] = eid
    return out


def get_claims_by_entity(
    conn: Connection,
    entity_ids: list[int],
    exclude_claim_ids: list[int] | None = None,
) -> dict[int, list[dict]]:
    """For each entity_id, fetch claims that already reference it.

    Used by the resolver to find supersedes / conflict candidates.
    Excludes the claims being resolved (avoid self-matches).
    """
    from psycopg.rows import dict_row  # noqa: PLC0415 — optional dependency ([postgresql] extra); imported where used so environments without it keep working

    if not entity_ids:
        return {}
    excl = exclude_claim_ids or []
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, memory_id, text, claim_type, entity_ids, supersedes,
                   extracted_at
              FROM wiki.claim_events
             WHERE entity_ids && %s::int[]
               AND (%s::bigint[] IS NULL OR NOT (id = ANY(%s::bigint[])))
            """,
            (list(entity_ids), excl or None, excl or None),
        )
        rows = list(cur.fetchall())
    out: dict[int, list[dict]] = {}
    for r in rows:
        # entity_ids returns as a list already (PG INT[] → Python list)
        for eid in r.get("entity_ids") or []:
            if eid in entity_ids:
                out.setdefault(eid, []).append(r)
    return out


def update_claim_entities(
    conn: Connection, updates: list[tuple[int, list[int]]]
) -> int:
    """Bulk update wiki.claim_events.entity_ids. Returns rows updated.

    Idempotent: only writes when the new list differs from the current.
    """
    if not updates:
        return 0
    written = 0
    with conn.cursor() as cur:
        for claim_id, eids in updates:
            cur.execute(
                """
                UPDATE wiki.claim_events
                   SET entity_ids = %s::int[]
                 WHERE id = %s
                   AND entity_ids IS DISTINCT FROM %s::int[]
                """,
                (eids, claim_id, eids),
            )
            written += cur.rowcount
    return written


def update_claim_supersedes(conn: Connection, updates: list[tuple[int, int]]) -> int:
    """Bulk update wiki.claim_events.supersedes. Returns rows updated.

    ``updates`` is [(new_claim_id, superseded_claim_id), ...].
    """
    if not updates:
        return 0
    written = 0
    with conn.cursor() as cur:
        for new_id, sup_id in updates:
            cur.execute(
                """
                UPDATE wiki.claim_events
                   SET supersedes = %s
                 WHERE id = %s
                   AND (supersedes IS NULL OR supersedes <> %s)
                """,
                (sup_id, new_id, sup_id),
            )
            written += cur.rowcount
    return written
