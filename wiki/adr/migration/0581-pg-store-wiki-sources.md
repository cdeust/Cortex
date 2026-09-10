---
kind: adr
number: 0581
title: Preserve pg_store_wiki_sources design decisions
status: accepted
---

# ADR-0581: pg_store_wiki_sources design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pg_store_wiki_sources.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
wiki.page_sources DB operations (ADR-0051 STEP 2 — the writer).
````

### module, original line 1

````text
Split out of ``pg_store_wiki.py`` (already ~874 lines, over the 300-line
file limit) rather than added there — coding-standards.md §4.1. Mirrors
the shape of ``pg_store_wiki.upsert_link``: an idempotent refresh scoped
by a key, matching how ``wiki_migrate.migrate_wiki`` already refreshes
``wiki.links`` via ``delete_links_from`` + re-insert per page.
````

### list_pages_missing_source_link, original line 25

````text
Pages with no primary 'documents' source link (ADR-0051 STEP 3).
````

### list_pages_missing_source_link, original line 25

````text
    Selects pages where ``documents_primary IS NULL`` (the fast-path
    mirror is unset) AND no ``wiki.page_sources`` row exists for that
    page with ``link_kind = 'documents'`` (the N:M source of truth is
    also empty) — both must be absent, matching the invariant
    ``upsert_page`` maintains between the two representations.
````

### list_pages_missing_source_link, original line 25

````text
    Pre-condition:  ``limit`` bounds the per-cycle scan so a large wiki
                    doesn't stall one ``consolidate`` invocation.
    Post-condition: every returned row's ``id`` refers to a page with
                    zero 'documents' rows in wiki.page_sources and a
                    NULL documents_primary.
    
````

### _entry_row, original line 66

````text
Build one INSERT row ``(page_id, path, link_kind, confidence, source)``.
````

### _entry_row, original line 66

````text
    A bare ``str`` entry uses the call's ``source``/``confidence``
    defaults (the original, still-supported shape — the ``documents``
    link_kind callers pass a uniform origin for the whole list). A
    ``tuple`` carries its own per-entry origin (ADR-0051 STEP 4: the
    ``references`` link_kind mixes ``claim_evidence`` and ``body``
    provenance in one call, which a single call-level ``source`` cannot
    express).
    
````

### upsert_page_sources, original line 94

````text
    ``documents`` entries: plain ``str`` uses the call's ``source``/
    ``confidence`` for every row (original shape, unchanged); a
    ``(path, source)`` / ``(path, source, confidence)`` tuple carries its
    own per-entry origin (additive, ADR-0051 STEP 4 — a single call now
    mixes provenances, e.g. 'references' mixing claim_evidence + body).
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.

### upsert_page_sources: completeness audit

````text
Idempotently replace a page's ``wiki.page_sources`` rows for one link_kind.

    Delete-then-insert scoped to ``(page_id, link_kind)`` — mirrors
    ``pg_store_wiki`` refreshing ``wiki.links``, so re-running the writer
    on an unchanged page produces the same rows (idempotent).

    Pre-condition:  page_id exists; every path is already canonical
                    (wiki_source_paths.normalize_source_path).
    Post-condition: wiki.page_sources has exactly one row per unique
                    path in ``documents`` for this (page_id, link_kind);
                    no prior-call row for that key survives.

    Returns the number of rows inserted.

source: ADR-0581
````
