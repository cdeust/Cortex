"""Wiki schema DB operations (Phase 1 of redesign).

Upserts and queries over wiki.pages / wiki.concepts / wiki.claim_events /
wiki.drafts / wiki.links / wiki.citations / wiki.memos.

Files on disk remain the source of truth for wiki.pages; this module
maintains the query index. All writes are idempotent (UPSERT by rel_path
or body_hash). Triggers on wiki.links and wiki.citations maintain the
denormalised counters on wiki.pages.

Pure infrastructure — no core imports, no handler imports.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row


# ── Hashing helper ─────────────────────────────────────────────────────


def body_hash(body: str) -> str:
    """Deterministic hash of a page body — drives idempotent upserts."""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# ── wiki.pages ─────────────────────────────────────────────────────────


def upsert_page(conn: Connection, page: dict[str, Any]) -> tuple[int, bool]:
    """Upsert a page row by rel_path.

    Returns ``(page_id, was_modified)`` where ``was_modified`` is True
    when the row was inserted or actually updated, False when the
    body_hash matched and nothing changed.

    Required fields: rel_path, slug, kind, title.
    Optional: all other columns.
    """
    required = ("rel_path", "slug", "kind", "title")
    for k in required:
        if k not in page:
            raise ValueError(f"upsert_page missing required field: {k}")

    body = page.get("body", "")
    bh = page.get("body_hash") or body_hash(body)

    # Use xmax=0 (Postgres trick) to detect INSERT vs UPDATE: xmax is 0
    # only on a fresh INSERT. We also OR in body_hash equality to detect
    # no-op updates that the WHERE clause filtered out.
    sql = """
    INSERT INTO wiki.pages (
        memory_id, concept_id, rel_path, slug, kind, title, domain, domains,
        tags, audience, requires, status, lifecycle_state, supersedes,
        superseded_by, verified, lead, sections, body_hash
    ) VALUES (
        %(memory_id)s, %(concept_id)s, %(rel_path)s, %(slug)s, %(kind)s,
        %(title)s, %(domain)s, %(domains)s::jsonb, %(tags)s::jsonb,
        %(audience)s::jsonb, %(requires)s::jsonb, %(status)s,
        %(lifecycle_state)s, %(supersedes)s, %(superseded_by)s, %(verified)s,
        %(lead)s, %(sections)s::jsonb, %(body_hash)s
    )
    ON CONFLICT (rel_path) DO UPDATE SET
        memory_id = EXCLUDED.memory_id,
        concept_id = EXCLUDED.concept_id,
        slug = EXCLUDED.slug,
        kind = EXCLUDED.kind,
        title = EXCLUDED.title,
        domain = EXCLUDED.domain,
        domains = EXCLUDED.domains,
        tags = EXCLUDED.tags,
        audience = EXCLUDED.audience,
        requires = EXCLUDED.requires,
        status = EXCLUDED.status,
        lifecycle_state = EXCLUDED.lifecycle_state,
        supersedes = EXCLUDED.supersedes,
        superseded_by = EXCLUDED.superseded_by,
        verified = EXCLUDED.verified,
        lead = EXCLUDED.lead,
        sections = EXCLUDED.sections,
        body_hash = EXCLUDED.body_hash,
        tended = NOW()
    WHERE wiki.pages.body_hash <> EXCLUDED.body_hash
    RETURNING id, (xmax = 0) AS inserted;
    """
    params = {
        "memory_id": page.get("memory_id"),
        "concept_id": page.get("concept_id"),
        "rel_path": page["rel_path"],
        "slug": page["slug"],
        "kind": page["kind"],
        "title": page["title"],
        "domain": page.get("domain", ""),
        "domains": json.dumps(page.get("domains", [])),
        "tags": json.dumps(page.get("tags", [])),
        "audience": json.dumps(page.get("audience", [])),
        "requires": json.dumps(page.get("requires", [])),
        "status": page.get("status", "seedling"),
        "lifecycle_state": page.get("lifecycle_state", "active"),
        "supersedes": page.get("supersedes"),
        "superseded_by": page.get("superseded_by"),
        "verified": page.get("verified"),
        "lead": page.get("lead", ""),
        "sections": json.dumps(page.get("sections", {})),
        "body_hash": bh,
    }
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        if row is not None:
            # Row was inserted or actually updated.
            if isinstance(row, dict):
                return row["id"], True
            return row[0], True
        # WHERE clause filtered the UPDATE out → body_hash matched, no-op.
        cur.execute(
            "SELECT id FROM wiki.pages WHERE rel_path = %s", (page["rel_path"],)
        )
        existing = cur.fetchone()
        if existing is None:
            return -1, False
        existing_id = existing["id"] if isinstance(existing, dict) else existing[0]
        return existing_id, False


def get_page_by_slug(conn: Connection, slug: str) -> dict | None:
    """Return a page row by slug, or None."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM wiki.pages WHERE slug = %s LIMIT 1", (slug,))
        return cur.fetchone()


def get_page_by_rel_path(conn: Connection, rel_path: str) -> dict | None:
    """Return a page row by rel_path, or None."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM wiki.pages WHERE rel_path = %s LIMIT 1", (rel_path,))
        return cur.fetchone()


# ── wiki.links ─────────────────────────────────────────────────────────


def upsert_link(
    conn: Connection,
    src_page_id: int,
    dst_slug: str,
    link_kind: str = "see-also",
    dst_page_id: int | None = None,
) -> None:
    """Insert a link, resolving dst_page_id by slug if not provided.

    ON CONFLICT DO UPDATE lets a stale dst_page_id be refreshed when
    the target page appears later.
    """
    if dst_page_id is None:
        p = get_page_by_slug(conn, dst_slug)
        dst_page_id = p["id"] if p else None

    sql = """
    INSERT INTO wiki.links (src_page_id, dst_slug, dst_page_id, link_kind)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (src_page_id, dst_slug, link_kind) DO UPDATE SET
        dst_page_id = EXCLUDED.dst_page_id
    WHERE wiki.links.dst_page_id IS DISTINCT FROM EXCLUDED.dst_page_id;
    """
    with conn.cursor() as cur:
        cur.execute(sql, (src_page_id, dst_slug, dst_page_id, link_kind))


def delete_links_from(conn: Connection, src_page_id: int) -> int:
    """Remove all outgoing links from a page (used before re-indexing)."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM wiki.links WHERE src_page_id = %s", (src_page_id,))
        return cur.rowcount


def get_backlinks(conn: Connection, dst_page_id: int) -> list[dict]:
    """Return rows linking TO this page."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT l.*, p.title AS src_title, p.rel_path AS src_rel_path
              FROM wiki.links l
              JOIN wiki.pages p ON p.id = l.src_page_id
             WHERE l.dst_page_id = %s
            """,
            (dst_page_id,),
        )
        return list(cur.fetchall())


def resolve_unresolved_links(conn: Connection) -> int:
    """Second-pass link resolution: fill in dst_page_id for links whose
    target didn't exist at insert time. Returns rows updated."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE wiki.links l
               SET dst_page_id = p.id
              FROM wiki.pages p
             WHERE p.slug = l.dst_slug
               AND l.dst_page_id IS NULL
            """
        )
        return cur.rowcount


# ── wiki.claim_events ──────────────────────────────────────────────────


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
            row = cur.fetchone()
            out.append(row["id"] if isinstance(row, dict) else row[0])
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
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM wiki.claim_events WHERE memory_id = %s ORDER BY id",
            (memory_id,),
        )
        return list(cur.fetchall())


# ── wiki.citations ─────────────────────────────────────────────────────


def insert_citation(
    conn: Connection,
    page_id: int,
    session_id: str = "",
    domain: str = "",
    memory_id: int | None = None,
) -> int:
    """Record that a page was cited. Trigger bumps heat + citation_count."""
    sql = """
    INSERT INTO wiki.citations (page_id, session_id, domain, memory_id)
    VALUES (%s, %s, %s, %s)
    RETURNING id;
    """
    with conn.cursor() as cur:
        cur.execute(sql, (page_id, session_id, domain, memory_id))
        row = cur.fetchone()
        return row["id"] if isinstance(row, dict) else row[0]


# ── wiki.memos (grounded-theory audit trail) ──────────────────────────


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
        row = cur.fetchone()
        return row["id"] if isinstance(row, dict) else row[0]


# ── Diagnostics ────────────────────────────────────────────────────────


def wiki_stats(conn: Connection) -> dict:
    """Counts across the wiki schema."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM wiki.pages) AS pages,
              (SELECT COUNT(*) FROM wiki.pages WHERE lifecycle_state='active') AS active,
              (SELECT COUNT(*) FROM wiki.pages WHERE lifecycle_state='archived') AS archived,
              (SELECT COUNT(*) FROM wiki.concepts) AS concepts,
              (SELECT COUNT(*) FROM wiki.drafts WHERE status='pending') AS pending_drafts,
              (SELECT COUNT(*) FROM wiki.claim_events) AS claim_events,
              (SELECT COUNT(*) FROM wiki.links) AS links,
              (SELECT COUNT(*) FROM wiki.citations) AS citations,
              (SELECT COUNT(*) FROM wiki.memos) AS memos
            """
        )
        return cur.fetchone()
