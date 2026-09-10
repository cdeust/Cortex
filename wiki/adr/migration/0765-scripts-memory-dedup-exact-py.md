# ADR-0765: scripts/memory_dedup_exact.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/memory_dedup_exact.py`; original SHA-256 `f550ee7320535690b35ad9e244ce3b70f897038cf4413962730aabc9a31b0476`.

## Original docstring, lines 2–26

````text
"""Collapse active memories with byte-identical content onto their
hottest member via supersession — I6-D1, INC6.3.

Runs ``handlers.consolidation.memory_dedup_exact_pass`` against the
shared store and writes a campaign journal artifact (dup_key, elected
survivor, superseded ids, group size, observed domains per group — the
same "journalisation" shape as ``memory_domain_backfill.py``, I6-D3).

Usage
-----

Dry-run (default) — group, elect, and report, write nothing::

    uv run python scripts/memory_dedup_exact.py

Apply the change to the DB::

    uv run python scripts/memory_dedup_exact.py --apply

The pass is idempotent: re-running after ``--apply`` finds zero groups
left to collapse (``current_memories`` no longer contains the superseded
rows, so the grouping query returns nothing for them), and never
supersedes a row that is not still an open chain head at write time
(``pg_store_memory_dedup.supersede_to_existing``'s CAS guard).
"""
````

