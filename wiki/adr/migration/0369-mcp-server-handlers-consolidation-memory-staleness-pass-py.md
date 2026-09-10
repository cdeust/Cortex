# ADR-0369: mcp_server/handlers/consolidation/memory_staleness_pass.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/consolidation/memory_staleness_pass.py`; original SHA-256 `0a8311f65219bb0293ec5e017686d2f9260d34b909cfd5b4ff2a42b00e05f95b`.

## Original docstring, lines 1–27

````text
"""Bounded file-existence staleness re-validation pass (fleet-watch #110).

``is_stale`` is the signal the injection banners now surface (age · grade ·
stale), but it only ever got *set* on file grounds by the manual
``validate_memory`` tool — so a memory referencing a file that was moved or
deleted stayed ``is_stale=FALSE`` until someone ran the tool by hand.
harness-comparison rev.2 measured exactly this: Harness B served facts months
stale with no stale flag.

This pass makes the flag fire automatically: it pages non-stale,
file-referencing memories, re-checks whether their referenced paths still
exist, and marks ``is_stale`` via the same pure assessment
(``core.staleness.assess_staleness``) and store method (``mark_memory_stale``)
the tool uses.

Deliberately **mark-only**: it never de-stales (rehabilitates) a memory. The
active-forgetting circuit (``consolidation/forgetting.py``, Rac1) also writes
``is_stale`` for non-file reasons; auto-rehabilitation here could fight it, so
de-staling stays with the explicit, human-invoked ``validate_memory`` tool.
Existence only — content-change detection (a file that still exists but diverged
from what the memory claims) needs per-ref content hashing and is a separate
#110 seam.

Composition root: pure decision (``assess_staleness``) + an injected filesystem
resolver + store I/O. Script-invoked (``scripts/memory_staleness_revalidate.py``),
bounded per run, NOT on the commit critical path or the hot consolidate cycle.
"""
````

## Original comment, lines 38–42

````text
# Per-run scan cap — bounds one run's FS+DB cost. A run that hits the cap
# resumes from the id cursor on the next invocation.
# source: mirrors DEFAULT_MEMORY_DOMAIN_BACKFILL_LIMIT = 5000
#   (memory_domain_backfill_pass.py) — a chosen per-run bound, not a measured
#   value; adjust with the corpus size.
````

## Original comment, lines 44–46

````text
# Page size for the id-cursor scan.
# source: get_all_memories_for_validation default page (pg_store_queries.py:94)
#   is 1000; reused here for parity with the existing validation read path.
````

