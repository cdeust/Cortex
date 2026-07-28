"""wiki.pages domain-backfill DB operations (Volet 4).

Reads catch-all pages and rewrites their ``domain`` column. Split into
its own module (rather than added to ``pg_store_wiki_pages.py``) to keep
each infrastructure file focused and under the size cap — no unrelated
function is reopened.

Pure infrastructure — no core imports, no handler imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from psycopg import Connection


def list_catchall_pages_with_sources(
    conn: Connection, known_domains: list[str], limit: int
) -> list[dict]:
    """Pages whose domain isn't a registered project, with source paths.

    Selects rows where ``domain`` is NULL or absent from
    ``known_domains`` (the repo registry's canonical names) — these are
    catch-all buckets (``uncategorized``, ``_general``, ``global``, ...)
    that a caller wants to re-derive via ``core.wiki_domain_backfill``.

    Pre-condition:  ``known_domains`` is the registered set of canonical
                    project domains; ``limit`` bounds the per-cycle scan.
    Post-condition: every returned row carries ``id``, ``domain`` (as
                    currently stored, possibly None), and
                    ``source_paths`` — the page's aggregated
                    ``wiki.page_sources.source_path`` values (empty list
                    when the page has none).
    """
    from psycopg.rows import dict_row

    sql = """
    SELECT p.id, p.domain,
           COALESCE(array_agg(ps.source_path)
                    FILTER (WHERE ps.source_path IS NOT NULL),
                    '{}') AS source_paths
      FROM wiki.pages p
      LEFT JOIN wiki.page_sources ps ON ps.page_id = p.id
     WHERE p.domain IS NULL OR NOT (p.domain = ANY(%(known)s))
     GROUP BY p.id, p.domain
     LIMIT %(limit)s
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"known": known_domains, "limit": limit})
        return list(cur.fetchall())


def update_page_domain(conn: Connection, page_id: int, domain: str) -> None:
    """Overwrite one page's ``domain`` column.

    Pre-condition:  ``page_id`` refers to an existing ``wiki.pages`` row.
    Post-condition: ``wiki.pages.domain`` equals ``domain`` for that row.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE wiki.pages SET domain = %s WHERE id = %s", (domain, page_id)
        )


__all__ = ["list_catchall_pages_with_sources", "update_page_domain"]
