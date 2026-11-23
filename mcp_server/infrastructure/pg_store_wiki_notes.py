"""wiki.citations / wiki.memos DB operations, and wiki-schema diagnostics.

Pure infrastructure — no core imports, no handler imports.

source: ADR-0579"""

from __future__ import annotations

from mcp_server.infrastructure.row_factory import DICT_ROW

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp_server.infrastructure.db_types import StoreConnection

import json


from mcp_server.infrastructure.pg_store_wiki_common import _returning_id


def insert_citation(
    conn: StoreConnection,
    page_id: int,
    session_id: str = "",
    domain: str = "",
    memory_id: int | None = None,
) -> int | None:
    """Record that a page was cited. Trigger bumps heat + citation_count.

    Precondition: page_id references an existing wiki.pages row. Postcondition: two
    independent dedup keys apply, both enforced by
        partial unique indexes (pg_schema.py):
          - (page_id, session_id) where session_id <> '' — "this page was
            read in this session" (CITED_IN semantics, T2-H4/D7/Q2). The INSERT omits an
            explicit conflict target (unqualified
        ``ON CONFLICT DO NOTHING``) so Postgres infers whichever partial
        index actually matches the row being inserted, without either
        write-path caller needing to know about the other's dedup key. Rows with
        session_id='' AND memory_id IS NULL carry no dedup
        semantics at all and always insert. Returns the new citation id, or None if
        either dedup key already
        had a matching row (duplicate, not an error).

    source: ADR-0579"""
    sql = """
    INSERT INTO wiki.citations (page_id, session_id, domain, memory_id)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT DO NOTHING
    RETURNING id;
    """
    with conn.cursor() as cur:
        cur.execute(sql, (page_id, session_id, domain, memory_id))
        row = cur.fetchone()
        return _returning_id(row) if row is not None else None


def delete_page_memory_citations(
    conn: StoreConnection, page_id: int, keep: list[int]
) -> int:
    """Drop the page's memory citations outside ``keep``; return the rows removed.

    Precondition: runs in the unit of a full write that names its sources
    (``wiki_write._sync_page_and_cite``); ``keep`` is that write's citable
    ids, not empty. Postcondition: every row of the page that names a memory
    outside ``keep`` is gone; rows naming a memory in ``keep`` and rows whose
    memory_id is NULL (a session read of the page) are kept. A row is kept,
    not deleted and inserted again, because PostgreSQL's citation trigger
    (``trg_wiki_citation_bump``) fires on INSERT only: each identical
    rewrite raised the page's ``citation_count`` and heat (review of PR
    #1110, note 1), and a deletion never lowers them.

    source: issue #715 (acceptance criterion 1)"""
    sql = """
    DELETE FROM wiki.citations
     WHERE page_id = %s AND memory_id IS NOT NULL
       AND NOT (memory_id = ANY(%s));
    """
    with conn.cursor() as cur:
        cur.execute(sql, (page_id, list(keep)))
        return int(cur.rowcount)


def list_page_cited_memory_ids(conn: StoreConnection, page_id: int) -> list[int]:
    """Distinct memory ids the page's ``wiki.citations`` rows name, first cited first.

    Precondition: page_id references a wiki.pages row. Postcondition: rows whose
    memory_id is NULL (a session read with no memory, or a memory deleted under
    ``ON DELETE SET NULL``) are left out: they name no memory to trace.

    source: issue #713 (slice 3)"""
    sql = """
    SELECT memory_id
    FROM wiki.citations
    WHERE page_id = %s AND memory_id IS NOT NULL
    GROUP BY memory_id
    ORDER BY MIN(id);
    """
    with conn.cursor(row_factory=DICT_ROW) as cur:
        cur.execute(sql, (page_id,))
        return [int(row["memory_id"]) for row in cur.fetchall()]


def list_pages_citing_memory(conn: StoreConnection, memory_id: int) -> list[str]:
    """Wiki-relative paths of the pages whose ``wiki.citations`` name the memory.

    Postcondition: distinct paths, sorted. Read before a hard forget erases the
    citation rows, it names the pages whose source trace loses that memory.

    source: issue #713 (slice 4)"""
    sql = """
    SELECT DISTINCT p.rel_path
    FROM wiki.citations c
    JOIN wiki.pages p ON p.id = c.page_id
    WHERE c.memory_id = %s
    ORDER BY p.rel_path;
    """
    with conn.cursor(row_factory=DICT_ROW) as cur:
        cur.execute(sql, (memory_id,))
        return [str(row["rel_path"]) for row in cur.fetchall()]


def insert_memo(
    conn: StoreConnection,
    subject_type: str,
    subject_id: int,
    decision: str,
    rationale: str = "",
    alternatives: list | None = None,
    inputs: dict | None = None,
    confidence: float = 0.5,
    author: str = "system",
) -> int:
    sql = """
    INSERT INTO wiki.memos (
        subject_type, subject_id, decision, rationale,
        alternatives, inputs, confidence, author
    )
    VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
    RETURNING id;
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                subject_type,
                subject_id,
                decision,
                rationale,
                json.dumps(alternatives or []),
                json.dumps(inputs or {}),
                confidence,
                author,
            ),
        )
        return _returning_id(cur.fetchone())


def list_uncited_deliberate_memories(
    conn: StoreConnection, limit: int = 20
) -> list[dict]:
    """Return uncited deliberate memories eligible for documentation, up to limit.
    Requires a provisioned wiki schema. Does not write pages or citations.

    source: ADR-0579"""
    sql = """
    SELECT m.id, LEFT(m.content, 200) AS content_preview, m.domain,
           m.importance, m.is_protected, m.source_attribution,
           m.created_at
    FROM current_memories m
    WHERE NOT m.is_stale
      AND m.source <> 'post_tool_capture'
      AND (
        m.is_protected
        OR m.importance >= 0.8
        OR m.source_attribution = 'verified'
      )
      AND NOT EXISTS (
        SELECT 1 FROM wiki.citations c
        WHERE c.memory_id = m.id
      )
    ORDER BY m.importance DESC, m.created_at DESC
    LIMIT %s;
    """
    with conn.cursor(row_factory=DICT_ROW) as cur:
        cur.execute(sql, (limit,))
        return list(cur.fetchall())


def wiki_stats(conn: StoreConnection) -> dict[str, Any]:
    """Counts across the wiki schema."""
    with conn.cursor(row_factory=DICT_ROW) as cur:
        cur.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM wiki.pages) AS pages,
              (SELECT COUNT(*) FROM wiki.pages
                WHERE lifecycle_state='active') AS active,
              (SELECT COUNT(*) FROM wiki.pages
                WHERE lifecycle_state='archived') AS archived,
              (SELECT COUNT(*) FROM wiki.concepts) AS concepts,
              (SELECT COUNT(*) FROM wiki.drafts
                WHERE status='pending') AS pending_drafts,
              (SELECT COUNT(*) FROM wiki.claim_events) AS claim_events,
              (SELECT COUNT(*) FROM wiki.links) AS links,
              (SELECT COUNT(*) FROM wiki.citations) AS citations,
              (SELECT COUNT(*) FROM wiki.memos) AS memos
            """
        )
        row = cur.fetchone()
        if row is None:
            # source: ADR-0579
            raise RuntimeError("wiki_stats aggregate SELECT produced no row")
        return dict(row)
