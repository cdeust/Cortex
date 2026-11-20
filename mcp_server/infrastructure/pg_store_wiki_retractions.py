"""wiki.page_retractions: a cited memory erased since the page was last written.

A hard ``forget`` deletes the memory's ``wiki.citations`` rows (ADR-1111), so
the page's source trace no longer names it and the page would read
``current`` on a text still written from it. One retraction row per page that
cited the erased memory keeps that fact without keeping the memory: the row
holds the page id and the time, never the memory id or any of its text. A
full write of the page (``create`` or ``replace``) is its refresh and clears
the rows; an ``append`` keeps them, since it removes nothing the page said.

Pure infrastructure — no core imports, no handler imports.

source: issue #715 (acceptance criterion 1)"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp_server.infrastructure.row_factory import DICT_ROW

if TYPE_CHECKING:
    from mcp_server.infrastructure.db_types import StoreConnection


def record_page_retractions(conn: StoreConnection, memory_id: int) -> int:
    """Add one retraction row per page whose citations name the memory.

    precondition: runs inside the erasure transaction, before the memory's
    ``wiki.citations`` rows are deleted. postcondition: each distinct page
    citing ``memory_id`` gains exactly one row; returns the number of rows
    added. A page the same erasure removes loses its rows by cascade.
    """
    sql = """
    INSERT INTO wiki.page_retractions (page_id)
    SELECT DISTINCT page_id FROM wiki.citations WHERE memory_id = %s;
    """
    with conn.cursor() as cur:
        cur.execute(sql, (memory_id,))
        return int(cur.rowcount)


def count_page_retractions(conn: StoreConnection, page_id: int) -> int:
    """Cited memories erased since the page's last full write."""
    sql = """
    SELECT COUNT(*) AS n FROM wiki.page_retractions WHERE page_id = %s;
    """
    with conn.cursor(row_factory=DICT_ROW) as cur:
        cur.execute(sql, (page_id,))
        return int(cur.fetchone()["n"])


def clear_page_retractions(conn: StoreConnection, page_id: int) -> None:
    """Drop the page's retractions: a full write refreshed its text."""
    sql = """
    DELETE FROM wiki.page_retractions WHERE page_id = %s;
    """
    with conn.cursor() as cur:
        cur.execute(sql, (page_id,))
