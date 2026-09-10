"""Pure infrastructure — no core imports, no handler imports.

source: ADR-0581"""

from __future__ import annotations

from mcp_server.infrastructure.row_factory import DICT_ROW

from collections.abc import Sequence

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_server.infrastructure.db_types import StoreConnection


def list_pages_missing_source_link(conn: StoreConnection, *, limit: int) -> list[dict]:
    """List pages without any primary documents source link.

    Pre-condition: limit bounds returned pages.

    Post-condition: every result has NULL documents_primary and no
    wiki.page_sources row with link_kind=documents.

    source: ADR-0581"""
    sql = """
    SELECT p.id, p.memory_id, p.rel_path, p.title, p.domain, p.lead, p.sections
      FROM wiki.pages p
     WHERE p.documents_primary IS NULL
       AND NOT EXISTS (
             SELECT 1 FROM wiki.page_sources s
              WHERE s.page_id = p.id AND s.link_kind = 'documents'
           )
     ORDER BY p.id
     LIMIT %s
    """
    with conn.cursor(row_factory=DICT_ROW) as cur:
        cur.execute(sql, (limit,))
        return list(cur.fetchall())


SourceEntry = str | tuple[str, str] | tuple[str, str, float]


def _entry_row(
    entry: SourceEntry,
    page_id: int,
    link_kind: str,
    *,
    default_source: str,
    default_confidence: float,
) -> tuple[int, str, str, float, str]:
    """Build one INSERT row ``(page_id, path, link_kind, confidence, source)``.

    source: ADR-0581"""
    match entry:
        case (path, entry_source, entry_confidence):
            return page_id, path, link_kind, entry_confidence, entry_source
        case (path, entry_source):
            return page_id, path, link_kind, default_confidence, entry_source
        case _:
            return page_id, entry, link_kind, default_confidence, default_source


def upsert_page_sources(
    conn: StoreConnection,
    page_id: int,
    documents: Sequence[SourceEntry],
    *,
    link_kind: str = "documents",
    source: str = "frontmatter",
    confidence: float = 1.0,
) -> int:
    """Replace a page’s source links for one link_kind.

    Pre-condition: page_id exists and all document paths are canonical.
    Entries may be plain paths, (path, source), or (path, source, confidence);
    plain paths use the call-level defaults.

    Post-condition: exactly one row per unique supplied path exists for
    (page_id, link_kind); previous rows for that key are removed. Return the
    number of inserted rows.

    source: ADR-0581"""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM wiki.page_sources WHERE page_id = %s AND link_kind = %s",
            (page_id, link_kind),
        )
        if not documents:
            return 0
        rows = [
            _entry_row(
                entry,
                page_id,
                link_kind,
                default_source=source,
                default_confidence=confidence,
            )
            for entry in documents
        ]
        cur.executemany(
            """
            INSERT INTO wiki.page_sources
                (page_id, source_path, link_kind, confidence, source)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (page_id, source_path, link_kind) DO UPDATE SET
                confidence = EXCLUDED.confidence,
                source = EXCLUDED.source
            """,
            rows,
        )
        return len(rows)
