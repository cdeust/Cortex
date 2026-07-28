"""wiki.page_sources DB operations (ADR-0051 STEP 2 — the writer).

Split out of ``pg_store_wiki.py`` (already ~874 lines, over the 300-line
file limit) rather than added there — coding-standards.md §4.1. Mirrors
the shape of ``pg_store_wiki.upsert_link``: an idempotent refresh scoped
by a key, matching how ``wiki_migrate.migrate_wiki`` already refreshes
``wiki.links`` via ``delete_links_from`` + re-insert per page.

Pure infrastructure — no core imports, no handler imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from psycopg import Connection


def list_pages_missing_source_link(conn: Connection, *, limit: int) -> list[dict]:
    """Pages with no primary 'documents' source link (ADR-0051 STEP 3).

    Selects pages where ``documents_primary IS NULL`` (the fast-path
    mirror is unset) AND no ``wiki.page_sources`` row exists for that
    page with ``link_kind = 'documents'`` (the N:M source of truth is
    also empty) — both must be absent, matching the invariant
    ``upsert_page`` maintains between the two representations.

    Pre-condition:  ``limit`` bounds the per-cycle scan so a large wiki
                    doesn't stall one ``consolidate`` invocation.
    Post-condition: every returned row's ``id`` refers to a page with
                    zero 'documents' rows in wiki.page_sources and a
                    NULL documents_primary.
    """
    from psycopg.rows import dict_row  # noqa: PLC0415 — optional dependency ([postgresql] extra); imported where used so environments without it keep working

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
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (limit,))
        return list(cur.fetchall())


SourceEntry = str | tuple[str, str] | tuple[str, str, float]

# source: structural — a (path, source, confidence) SourceEntry tuple has
# three elements; shorter tuples fall back to the call-level defaults
_ENTRY_WITH_CONFIDENCE = 3


def _entry_row(
    entry: SourceEntry,
    page_id: int,
    link_kind: str,
    *,
    default_source: str,
    default_confidence: float,
) -> tuple[int, str, str, float, str]:
    """Build one INSERT row ``(page_id, path, link_kind, confidence, source)``.

    A bare ``str`` entry uses the call's ``source``/``confidence``
    defaults (the original, still-supported shape — the ``documents``
    link_kind callers pass a uniform origin for the whole list). A
    ``tuple`` carries its own per-entry origin (ADR-0051 STEP 4: the
    ``references`` link_kind mixes ``claim_evidence`` and ``body``
    provenance in one call, which a single call-level ``source`` cannot
    express).
    """
    if isinstance(entry, tuple):
        path = entry[0]
        entry_source = entry[1] if len(entry) > 1 else default_source
        entry_confidence = (
            entry[2] if len(entry) >= _ENTRY_WITH_CONFIDENCE else default_confidence
        )
        return page_id, path, link_kind, entry_confidence, entry_source
    return page_id, entry, link_kind, default_confidence, default_source


def upsert_page_sources(
    conn: Connection,
    page_id: int,
    documents: list[SourceEntry],
    *,
    link_kind: str = "documents",
    source: str = "frontmatter",
    confidence: float = 1.0,
) -> int:
    """Idempotently replace a page's ``wiki.page_sources`` rows for one link_kind.

    Delete-then-insert scoped to ``(page_id, link_kind)`` — mirrors
    ``pg_store_wiki`` refreshing ``wiki.links``, so re-running the writer
    on an unchanged page produces the same rows (idempotent).

    ``documents`` entries: plain ``str`` uses the call's ``source``/
    ``confidence`` for every row (original shape, unchanged); a
    ``(path, source)`` / ``(path, source, confidence)`` tuple carries its
    own per-entry origin (additive, ADR-0051 STEP 4 — a single call now
    mixes provenances, e.g. 'references' mixing claim_evidence + body).

    Pre-condition:  page_id exists; every path is already canonical
                    (wiki_source_paths.normalize_source_path).
    Post-condition: wiki.page_sources has exactly one row per unique
                    path in ``documents`` for this (page_id, link_kind);
                    no prior-call row for that key survives.

    Returns the number of rows inserted.
    """
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
