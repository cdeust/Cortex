"""wiki.pages DB operations — CRUD and lookups.

Split out of ``pg_store_wiki.py`` (originally 890 lines, over the
300-line file limit — CLAUDE.md "Code Quality Rules") purely for size
compliance; no logic changed.

Pure infrastructure — no core imports, no handler imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp_server.infrastructure.db_types import StoreConnection

import json


from mcp_server.infrastructure.pg_store_wiki_common import body_hash
from mcp_server.infrastructure.pg_store_wiki_sources import upsert_page_sources


def upsert_page(conn: StoreConnection, page: dict[str, Any]) -> tuple[int, bool]:
    """Upsert a page row by rel_path.

    Returns ``(page_id, was_modified)`` where ``was_modified`` is True
    when the row was inserted or actually updated, False when the
    body_hash matched and nothing changed.

    Required fields: rel_path, slug, kind, title.
    Optional: all other columns, including ``documents`` (list of
    canonical source-file paths — ADR-0051) and ``documents_primary``
    (defaults to the first entry of ``documents`` when omitted).
    ``wiki.page_sources`` is refreshed unconditionally (even on a
    body_hash no-op) so a frontmatter-only edit still lands, matching
    how ``wiki.links`` is refreshed independently of body_hash in
    ``wiki_migrate.migrate_wiki``.
    """
    required = ("rel_path", "slug", "kind", "title")
    for k in required:
        if k not in page:
            raise ValueError(f"upsert_page missing required field: {k}")

    body = page.get("body", "")
    bh = page.get("body_hash") or body_hash(body)
    documents = page.get("documents") or []
    documents_primary = page.get("documents_primary") or (
        documents[0] if documents else None
    )

    # Use xmax=0 (Postgres trick) to detect INSERT vs UPDATE: xmax is 0
    # only on a fresh INSERT. We also OR in body_hash equality to detect
    # no-op updates that the WHERE clause filtered out.
    sql = """
    INSERT INTO wiki.pages (
        memory_id, concept_id, rel_path, slug, kind, title, domain, domains,
        tags, audience, requires, status, lifecycle_state, supersedes,
        superseded_by, verified, lead, sections, body_hash, documents_primary
    ) VALUES (
        %(memory_id)s, %(concept_id)s, %(rel_path)s, %(slug)s, %(kind)s,
        %(title)s, %(domain)s, %(domains)s::jsonb, %(tags)s::jsonb,
        %(audience)s::jsonb, %(requires)s::jsonb, %(status)s,
        %(lifecycle_state)s, %(supersedes)s, %(superseded_by)s, %(verified)s,
        %(lead)s, %(sections)s::jsonb, %(body_hash)s, %(documents_primary)s
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
        documents_primary = EXCLUDED.documents_primary,
        tended = NOW()
    WHERE wiki.pages.body_hash <> EXCLUDED.body_hash
       OR wiki.pages.documents_primary IS DISTINCT FROM EXCLUDED.documents_primary
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
        "documents_primary": documents_primary,
    }
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        if row is not None:
            # Row was inserted or actually updated.
            page_id = row["id"] if isinstance(row, dict) else row[0]
            upsert_page_sources(conn, page_id, documents)
            return page_id, True
        # WHERE clause filtered the UPDATE out → body_hash matched, no-op.
        cur.execute(
            "SELECT id FROM wiki.pages WHERE rel_path = %s", (page["rel_path"],)
        )
        existing = cur.fetchone()
        if existing is None:
            return -1, False
        existing_id = existing["id"] if isinstance(existing, dict) else existing[0]
        upsert_page_sources(conn, existing_id, documents)
        return existing_id, False


def list_all_rel_paths(conn: StoreConnection) -> list[str]:
    """Return every rel_path currently stored in wiki.pages.

    Used by the migration reconciliation phase to compute which rows
    no longer have a backing file on disk (see wiki_migrate.purge_ghost_pages).
    """
    with conn.cursor() as cur:
        cur.execute("SELECT rel_path FROM wiki.pages")
        rows = cur.fetchall()
    return [r["rel_path"] if isinstance(r, dict) else r[0] for r in rows]


def delete_pages_by_rel_path(conn: StoreConnection, rel_paths: list[str]) -> list[dict]:
    """Delete wiki.pages rows for the given rel_paths.

    Cascades to wiki.links (src_page_id ON DELETE CASCADE), wiki.page_sources
    (page_id ON DELETE CASCADE), and wiki.citations (page_id ON DELETE CASCADE)
    per the FKs declared in pg_schema.py — no separate DELETE against those
    tables is needed here.

    Precondition: rel_paths identifies rows the caller has already decided
    are safe to remove (e.g. no longer present on the filesystem).
    Postcondition: every wiki.pages row matching rel_paths is gone; rows not
    matching are untouched. Returns the deleted (id, rel_path) rows so the
    caller can report exactly what was purged.
    """
    if not rel_paths:
        return []
    from psycopg.rows import dict_row  # noqa: PLC0415 — optional dependency ([postgresql] extra); imported where used so environments without it keep working

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "DELETE FROM wiki.pages WHERE rel_path = ANY(%s) RETURNING id, rel_path",
            (list(rel_paths),),
        )
        return list(cur.fetchall())


def get_page_by_slug(conn: StoreConnection, slug: str) -> dict | None:
    """Return a page row by slug, or None."""
    from psycopg.rows import dict_row  # noqa: PLC0415 — optional dependency ([postgresql] extra); imported where used so environments without it keep working

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM wiki.pages WHERE slug = %s LIMIT 1", (slug,))
        return cur.fetchone()


def get_page_by_rel_path(conn: StoreConnection, rel_path: str) -> dict | None:
    """Return a page row by rel_path, or None."""
    from psycopg.rows import dict_row  # noqa: PLC0415 — optional dependency ([postgresql] extra); imported where used so environments without it keep working

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM wiki.pages WHERE rel_path = %s LIMIT 1", (rel_path,))
        return cur.fetchone()
