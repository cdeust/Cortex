# ADR-0792: scripts/wiki_citation_seed.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/wiki_citation_seed.py`; original SHA-256 `a8ebbba4e799d7c5c9a864e5325a944746a3844dac2bde370ad3174db1018ecf`.

## Original docstring, lines 2–42

````text
"""Seed ``wiki.citations`` for pages created before the flow-forward
write-path landed — M-D7, INC7.7.

Runs ``handlers.consolidation.wiki_citation_seed_pass`` against the
shared store and writes a campaign journal artifact (page_id, memory_id,
domain, reliability tier, outcome per row — the same journalisation
shape as ``memory_reheat.py``, I6-D5).

Scope (see the campaign report / ``core.wiki_citation_seed`` module
docstring for the full reliability audit): only the HIGH-reliability
source is seeded — pages whose ``wiki.pages.memory_id`` already carries
an FK-constrained pointer to their authoring memory. ``wiki.page_sources``
(file edges) and inferred tags/links are deliberately EXCLUDED — they
cannot produce a memory_id without fabricating provenance.

Usage
-----

Dry-run (default) — scan, decide, and report, write nothing::

    uv run python scripts/wiki_citation_seed.py

Apply the change to the DB::

    uv run python scripts/wiki_citation_seed.py --apply

Rollback (if ``--apply`` needs to be undone) — every row this campaign
writes is uniquely identifiable by the journal's ``(page_id, memory_id)``
pairs and by ``domain = ''`` OR any domain string this script recorded
(session_id is always ``''`` for this campaign, distinguishing it from
CITED_IN rows written by ``wiki_read``, whose partial unique index
requires ``session_id <> ''``)::

    DELETE FROM wiki.citations
    WHERE session_id = ''
      AND (page_id, memory_id) IN (<pairs from the journal artifact>);

The pass is idempotent: re-running after ``--apply`` finds every seeded
pair already in ``wiki.citations``, so ``seeded`` is 0 on immediate
re-run (confirmed by this campaign's idempotence test).
"""
````

