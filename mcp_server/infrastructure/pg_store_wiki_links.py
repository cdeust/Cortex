"""wiki.links DB operations.

Split out of ``pg_store_wiki.py`` (originally 890 lines, over the
300-line file limit — CLAUDE.md "Code Quality Rules") purely for size
compliance; no logic changed.

Pure infrastructure — no core imports, no handler imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from psycopg import Connection


from mcp_server.infrastructure.pg_store_wiki_pages import get_page_by_slug


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
    from psycopg.rows import dict_row  # noqa: PLC0415 — optional dependency ([postgresql] extra); imported where used so environments without it keep working

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
