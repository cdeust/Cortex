# ADR-0380: mcp_server/handlers/consolidation/wiki_source_backfill_pass.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/consolidation/wiki_source_backfill_pass.py`; original SHA-256 `311b83d016a64ea0da5d380673e934a7d98d06e9aa4481f9ed1008b0d58a34b9`.

## Original docstring, lines 1–14

````text
"""Backfill pass: derive + persist primary wiki page -> source-file links
for pages whose frontmatter never declared one (ADR-0051 STEP 3).

Composition root — wires ``core.wiki_source_backfill`` (pure derivation)
to infrastructure (DB reads/writes via ``pg_store_wiki_sources`` /
``pg_store_wiki_thermo``, filesystem existence checks via
``wiki_drift._file_exists_under``) under ``run_wiki_maintenance``'s
non-fatal try/except contract. Split out of ``wiki_maintenance.py`` to
keep both files under the 300-line cap (coding-standards.md §4.1).

Scope: strictly the primary ``'documents'`` link_kind. Persisting
``'references'`` (the per-page cited-symbol graph ``wiki_consolidate``
already computes and discards) is Étape 4 — out of scope here.
"""
````

## Original comment, lines 31–34

````text
# Per-cycle scan cap — mirrors MAX_PURGES_PER_CYCLE's rationale in
# wiki_maintenance.py: bounds one consolidate cycle's cost; pages left
# over are picked up by the next cycle (list_pages_missing_source_link
# only returns pages that are STILL unlinked, so nothing is skipped).
````

