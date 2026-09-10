# ADR-0376: mcp_server/handlers/consolidation/wiki_backlog_pass.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/consolidation/wiki_backlog_pass.py`; original SHA-256 `7a68e3e8a0274a9a38127bbefb5b1c0b8f647916341574f92a9599aeed52eb63`.

## Original docstring, lines 1–24

````text
"""Curation-backlog count for ``run_wiki_maintenance``.

Split out of ``wiki_maintenance.py`` to keep both files under the
300-line cap (coding-standards.md §4.1) — no logic changed from what
previously lived inline in that module's "Curation backlog" block.

Composition root — wires ``core.auto_curator`` / ``core.wiki_coverage`` /
``core.wiki_drift`` (pure logic) to the memory store's decay-chunk
iterator and the filesystem wiki root.

G-2 grooming (2026-07-11): also reports the ``lesson_promotion``
candidate backlog (mechanical ``COUNT(*)``, ~76ms measured, zero
judgment — see ``pg_store_lesson_promotion.count_lesson_promotion_
candidates``'s docstring). ``curate_distill``'s backlog is deliberately
NOT reported here: its ``total_dossiers_eligible`` requires running the
same entity/co-access clustering the full job-building handler runs
(measured ~2.6s against the dev corpus, dominated by
``core.auto_curator.build_clusters`` over a 500-memory pool) — there is
no cheap ``COUNT(*)`` path for it without duplicating that clustering
work, and running it on every consolidate cycle (up to 47/day measured,
``consolidation_log``) would add tens of seconds of egress per day for
a number nobody acts on without calling the tool anyway. Call
``curate_distill`` directly for that count; it does its own accounting.
"""
````

## Original comment, lines 98–101

````text
# File-level coverage: count files that aren't referenced anywhere
    # in the wiki. Aggregated across every domain that has a resolvable
    # source root. This is "nothing left uncovered" measured at the
    # file granularity.
````

