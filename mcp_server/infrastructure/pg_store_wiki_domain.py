"""wiki.pages domain-backfill DB operations (Volet 4).

Pure infrastructure — no core imports, no handler imports.

source: ADR-0576"""

from __future__ import annotations

from mcp_server.infrastructure.row_factory import DICT_ROW

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_server.infrastructure.db_types import StoreConnection


def list_catchall_pages_with_sources(
    conn: StoreConnection, known_domains: list[str], limit: int
) -> list[dict]:
    """List pages whose domain is NULL or absent from known_domains.

    Pre-condition: known_domains contains canonical project domains; limit
    bounds returned pages.

    Post-condition: each result contains id, the stored domain, and aggregated
    source_paths (an empty list when no source paths exist).

    source: ADR-0576"""
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
    with conn.cursor(row_factory=DICT_ROW) as cur:
        cur.execute(sql, {"known": known_domains, "limit": limit})
        return list(cur.fetchall())


def update_page_domain(conn: StoreConnection, page_id: int, domain: str) -> None:
    """Set one wiki page’s domain.

    Pre-condition: page_id identifies an existing wiki.pages row.

    Post-condition: that row’s domain equals the supplied domain.

    source: ADR-0576"""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE wiki.pages SET domain = %s WHERE id = %s", (domain, page_id)
        )


__all__ = ["list_catchall_pages_with_sources", "update_page_domain"]
