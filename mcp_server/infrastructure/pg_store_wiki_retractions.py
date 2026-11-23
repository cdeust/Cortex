"""wiki.page_retractions: a cited memory erased since the page was last written.

A hard ``forget`` deletes the memory's ``wiki.citations`` rows (ADR-1111), so
the page's source trace no longer names it and the page would read
``current`` on a text still written from it. One retraction row per page that
cited the erased memory keeps that fact without keeping the memory: the row
holds the page id and the time, never the memory id or any of its text. A
full write of the page (``create`` or ``replace``) that changes it is its
refresh and clears the rows recorded before it began (its frontier, read
before the file is written); an ``append`` keeps them, since it removes
nothing the page said, and so does a full write that leaves the page as it
was.

Pure infrastructure — no core imports, no handler imports.

source: issue #715 (acceptance criterion 1)"""

from __future__ import annotations

from typing import TYPE_CHECKING

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
    """Cited memories erased since the page's last full write.

    precondition: ``conn`` is a store connection, whose rows are read by
    column name on both backends: PostgreSQL's ``db_connect`` sets
    ``row_factory=dict_row``; SQLite's rows are ``sqlite3.Row`` through the
    compat cursor.
    """
    sql = """
    SELECT COUNT(*) AS n FROM wiki.page_retractions WHERE page_id = %s;
    """
    with conn.cursor() as cur:
        cur.execute(sql, (page_id,))
        return int(cur.fetchone()["n"])


def page_retractions_frontier(conn: StoreConnection) -> int:
    """The id of the last retraction recorded so far, 0 when there is none.

    A full write reads it before it writes the file: a retraction with a
    higher id was recorded by a hard ``forget`` that ran while the write was
    in progress, after the write began, so the write cannot be its
    refresh (Codex review of PR #1109). A ``forget`` that lands after the
    caller composed the text but before the write began sits below it and
    is cleared, although the text may rest on the erased memory (review of
    PR #1111, note 1). Ids come from the table's own
    sequence (``BIGSERIAL`` / ``AUTOINCREMENT``), never from a clock. Bound
    on PostgreSQL: an id is taken at insert, so a retraction whose erasure
    had not committed when the frontier was read, while a later one had,
    sits below the frontier and is cleared; that takes two erasures
    overlapping the read. SQLite writes one transaction at a time.
    precondition: ``conn`` is a store connection read by column name.
    """
    sql = """
    SELECT COALESCE(MAX(id), 0) AS n FROM wiki.page_retractions;
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        return int(cur.fetchone()["n"])


def clear_page_retractions(conn: StoreConnection, page_id: int, frontier: int) -> None:
    """Drop the page's retractions up to ``frontier``: a full write refreshed them.

    precondition: ``frontier`` is ``page_retractions_frontier`` read before
    the write's file was written. postcondition: every retraction of the
    page with an id above ``frontier`` is kept, so a hard ``forget`` that
    ran during the write still leaves the page ``pending``.
    """
    sql = """
    DELETE FROM wiki.page_retractions WHERE page_id = %s AND id <= %s;
    """
    with conn.cursor() as cur:
        cur.execute(sql, (page_id, frontier))
