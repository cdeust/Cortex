# ADR-0462: mcp_server/handlers/wiki_memory_sync.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/wiki_memory_sync.py`; original SHA-256 `81a00a04dc266ea09e39706a8a29b0955f2d270201d6176ece05c15c6f347f72`.

## Original docstring, lines 1–14

````text
"""Composition root: promote a stored memory to an authored wiki page.

Split out of ``infrastructure.wiki_store`` (layer fix: infrastructure/
must not import core/ — ``core.wiki_sync.build_from_memory`` runs the v2
classifier, real domain judgment, not a pure I/O-free helper the way
``wiki_store``'s other page-generation dependencies are). This module is
the composition root that wires the two together: it is the ONLY place
that both decides (core) and persists (infrastructure) a memory's wiki
page, exactly the role handlers/ exists for.

``sync_memory_strict``/``sync_memory`` keep their pre-move names and
contracts — moved, not rewritten — so callers (``handlers.remember``)
and their tests need only an import-path change, not a behavior change.
"""
````

## Original docstring, lines 33–55

````text
"""Strict variant of ``sync_memory`` — surfaces errors to the caller.

    Preconditions:
        - ``content`` is a non-empty string.
        - ``memory_id`` has already been committed to the store.

    Postconditions:
        - On success: returns the relative path of the written wiki page.
        - On classifier rejection: returns None (not an error — the memory
          did not qualify for a wiki page).
        - On I/O or classifier failure: raises the underlying exception.
          The caller must decide whether the memory write + wiki failure
          constitutes a partial failure.

    This is the E8 fix path: the wiki sync is a post-write side effect and
    must not destroy observability. Callers on the ``remember`` hot path
    wrap this in a narrow try/except that surfaces the failure as a
    ``warnings`` field in the response, rather than silently swallowing it.

    Does NOT swallow the reindex failure either — reindex is best-effort
    by design (see ``wiki_reindex_io.try_reindex``), but the page write
    itself must succeed or be reported.
    """
````

## Original docstring, lines 75–84

````text
"""Promote a stored memory to a wiki page if it passes the classifier.

    Backwards-compatible wrapper: swallows exceptions and returns None on
    error, for callers that cannot handle wiki-sync failure. New code
    should prefer ``sync_memory_strict`` and surface failures explicitly
    (see ADR-0045 / Taleb fragility audit: silent failure is worst-of-both).

    Returns the relative path of the written page, or None when the
    memory is rejected or on error.
    """
````

