"""wiki.citations / wiki.memos DB operations, and wiki-schema diagnostics.

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


def insert_citation(
    conn: Connection,
    page_id: int,
    session_id: str = "",
    domain: str = "",
    memory_id: int | None = None,
) -> int | None:
    """Record that a page was cited. Trigger bumps heat + citation_count.

    Precondition: page_id references an existing wiki.pages row.
    Postcondition: two independent dedup keys apply, both enforced by
    partial unique indexes (pg_schema.py):
      - (page_id, session_id) where session_id <> '' — "this page was
        read in this session" (CITED_IN semantics, T2-H4/D7/Q2). The
        +0.05 heat bump on trg_wiki_citation_bump must not repeat per
        re-read within one session.
      - (page_id, memory_id) where memory_id IS NOT NULL — "this
        memory was reported as used to author/re-curate this page"
        (DOCUMENTS semantics, I6-D7/INC6.8). A re-curation reporting
        the same memory again for the same page must not grow the
        table.
    The INSERT omits an explicit conflict target (unqualified
    ``ON CONFLICT DO NOTHING``) so Postgres infers whichever partial
    index actually matches the row being inserted, without either
    write-path caller needing to know about the other's dedup key.
    Rows with session_id='' AND memory_id IS NULL carry no dedup
    semantics at all and always insert.
    Returns the new citation id, or None if either dedup key already
    had a matching row (duplicate, not an error).
    """
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


def insert_memo(
    conn: Connection,
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


def list_uncited_deliberate_memories(conn: Connection, limit: int = 20) -> list[dict]:
    """List active, deliberate, verifiably-important memories with zero
    wiki.citations rows — I6-D7's reverse loop ("orphelines délibérées").

    Precondition: none (works on any wiki-schema-provisioned DB, even
    with zero citations rows).
    Postcondition: returns candidates for documentation, READ-ONLY —
    this function never writes a page or a citation; it is a report,
    not an action (D7 arbitrage: "pas d'écriture automatique de
    pages").

    "Deliberate" mirrors ``core.write_post_store._AUTO_CAPTURE_SOURCES``
    (currently the sole canonical auto-capture source, 'post_tool_
    capture') rather than importing that private module-level constant
    across a core/infrastructure boundary for one string. "Important"
    is a disjunction over the signals available on the memories table
    TODAY: is_protected (anchor.py sets this), importance >= 0.8, or
    source_attribution = 'verified'. I6-D6 (validate_memory's
    provenance grader, a sibling increment) is expected to populate
    source_attribution with real 'verified'/'verifiable'/'unverifiable'
    values — this query already reads that column so it benefits
    automatically once D6 lands, without needing a schema change here.
    """
    from psycopg.rows import dict_row  # noqa: PLC0415 — optional dependency ([postgresql] extra); imported where used so environments without it keep working

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
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (limit,))
        return list(cur.fetchall())


def wiki_stats(conn: Connection) -> dict:
    """Counts across the wiki schema."""
    from psycopg.rows import dict_row  # noqa: PLC0415 — optional dependency ([postgresql] extra); imported where used so environments without it keep working

    with conn.cursor(row_factory=dict_row) as cur:
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
        return cur.fetchone()
