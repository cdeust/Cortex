# ADR-0456: mcp_server/handlers/wiki_consolidate_staleness.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/wiki_consolidate_staleness.py`; original SHA-256 `7fb84a6d8973eafab1a97fd3d3b5a4ed301afc50e3b8941c8463154574eed503`.

## Original docstring, lines 1–15

````text
"""Wiki Phase 4, Pass 2 — staleness brake + reference-link persistence.

Split out of ``wiki_consolidate.py`` to keep both files under the
300-line cap and the orchestrator's ``handler()`` under the 50-line cap
(coding-standards.md §4.1/§4.2). Composition root — wires
``core.wiki_staleness`` (pure derivation) against ``pg_store_wiki`` /
``pg_store_wiki_sources`` (persistence). ``wiki_consolidate.handler``
still owns Pass 1 (decay/lifecycle) and Pass 3 (the final response
shape); this module owns exactly Pass 2.

ADR-0051 STEP 4: alongside the pre-existing staleness verdict, this pass
now persists every harvested file ref as a ``wiki.page_sources`` row
(``link_kind='references'``) so the file <-> wiki graph exposes every
file a page cites, not just its one 'documents' primary.
"""
````

## Original docstring, lines 61–89

````text
"""Persist harvested file refs as ``link_kind='references'`` rows.

    One ``upsert_page_sources`` call per page (delete-then-insert scoped
    to ``(page_id, 'references')`` — see that function's docstring for
    why this is idempotent). Runs for every page in this cycle's batch,
    not just pages with refs: a page whose refs dropped to zero must
    still have its stale rows cleared, which the empty-list branch of
    ``upsert_page_sources`` already does.

    Decision (ADR-0051 STEP 4): confidence is left at the function
    default (1.0) for every row regardless of origin (claim_evidence vs
    body). ``wiki_source_backfill_pass.py`` sets the same uniform 1.0
    across its own three origin tags for 'documents' — there is no
    existing precedent or measured basis (coding-standards.md §8) for a
    differentiated per-origin confidence, so inventing one here would be
    an unsourced constant. ``source`` (the origin tag) is still recorded
    per-row and is what a future differentiation would key off.

    Pre-condition:  every dict in ``per_page_typed_refs`` maps a page id
                    (present in ``pages``) to a raw (pre-normalization)
                    path -> origin mapping, as returned by
                    ``harvest_page_refs_typed``.
    Post-condition: for every page, wiki.page_sources' 'references' rows
                    equal exactly the normalized (deduplicated,
                    claim-wins) set of that page's harvested refs; no
                    stale 'references' row from a prior cycle survives.

    Returns the total number of rows written across all pages.
    """
````

## Original docstring, lines 101–106

````text
"""Harvest typed refs for every page; return (typed, plain, all-refs-union).

    Keeping per-path provenance (the first return value) lets the caller
    both check staleness (the plain sorted-list form) and persist
    'references' rows (path + origin) from one harvest pass.
    """
````

## Original docstring, lines 146–158

````text
"""Evaluate staleness for ``pages`` and, if not ``dry_run``, persist it.

    Pre-condition:  ``pages`` is the same page batch Pass 1 evaluated
                    this cycle (each dict carries at least id, lead,
                    sections, is_stale).
    Post-condition: when ``dry_run`` is False, wiki.pages.is_stale
                    reflects each page's verdict and wiki.page_sources
                    carries that page's current 'references' rows;
                    when True, no row is written and the returned
                    summary still reflects what *would* be written.

    Returns the ``staleness`` summary dict for the handler's response.
    """
````

