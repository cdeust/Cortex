# ADR-0475: mcp_server/handlers/wiki_write.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/wiki_write.py`; original SHA-256 `19ae4c23b15b9b59a1f35e59f6f75902edb148393639a2cdd800ded3574acac5`.

## Original docstring, lines 1–27

````text
"""Handler: wiki_write — author a new wiki page or update an existing one.

Composition root for the authoring path. Renders templated content via
``core.wiki_pages`` when a ``kind`` is supplied, then delegates the
atomic write to ``infrastructure.wiki_store``. After a successful write,
stores a protected PG pointer memory tagged ``wiki`` so ``recall`` can
surface the page like any other memory.

I6-D7/INC6.8 ("flux avant" citations): this is the completion handler
for ``curate_wiki``'s authoring jobs — the in-session LLM reads a job's
``memory_ids``/``supporting_memory_ids``, decides which of them it
actually used while authoring, and passes THAT subset back here via
``memory_ids``. Two additional best-effort side effects fire after a
successful write, mirroring ``wiki_read``'s ``_cite_page`` contract
(same degrade-to-no-op discipline, same "the write already succeeded
on disk, this is pure observability" boundary):

  1. Sync the page into ``wiki.pages`` synchronously (reuses
     ``wiki_migrate.page_row_from_md`` + ``upsert_page`` — the same
     row-shape ``wiki_migrate``'s batch sweep would produce later).
     Without this, ``wiki.citations`` would have no ``page_id`` to
     attach to until the next migration sweep ran.
  2. If ``memory_ids`` was passed, insert one ``wiki.citations`` row
     per memory_id — dedup key is ``(page_id, memory_id)``, distinct
     from ``wiki_read``'s ``(page_id, session_id)`` key (see
     ``insert_citation``'s docstring, pg_store_wiki_notes.py).
"""
````

## Original docstring, lines 257–262

````text
"""Write global wiki content and best-effort pointer/citation metadata.

    Source: ADR-0056 (governance contract). Storage normalizes frontmatter;
    malformed open fences propagate, while ordinary write errors are returned.
    Project branch publication uses project_wiki instead to avoid global state.
    """
````

## Original comment, lines 270–273

````text
# Propagate uncaught (see docstring) — narrower than the ValueError
        # catch below, which must not swallow this one. write_page now
        # raises it from its own normalize_frontmatter call (issue #110
        # moved that call down from this function).
````

## Original comment, lines 282–284

````text
# Advisory prose measurement (issue #166): generated pages carry an
    # AI-writing-tell report so authoring quality is visible at write time.
    # Never blocks the write; empty report is omitted to keep responses lean.
````

