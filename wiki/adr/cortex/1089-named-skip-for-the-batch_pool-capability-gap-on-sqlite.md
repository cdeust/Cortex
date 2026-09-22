---
created: 2026-09-22T23:43:24Z
kind: adr
number: 1089
status: accepted
tags: [consolidate, sqlite, batch_pool, wiki, issue-636]
title: Named skip for the batch_pool capability gap on SQLite
---
# ADR-1089: Named skip for the batch_pool capability gap on SQLite

## Status

accepted

## Context

consolidate's wiki maintenance cycle runs four passes on every invocation --
wiki_source_backfill_pass, wiki_domain_backfill_pass, wiki_citation_seed_pass,
and wiki_backlog_pass's lesson-promotion count -- each of which needs
store.batch_pool, a psycopg_pool.ConnectionPool that only PgMemoryStore
provides, because the SQL they run is Postgres-schema-qualified
(wiki.pages, wiki.citations, %s placeholders) with no SQLite equivalent.
SqliteMemoryStore -- the zero-config default backend -- simply has no
batch_pool attribute, so every one of these passes raised AttributeError on
every SQLite install, on every run.

Three of the four passes already caught that AttributeError internally and
returned {"status": "error: AttributeError: ..."} instead of letting it
propagate. wiki_maintenance.py's own escalation logic only bumped
out["status"] away from "ok" when a sub-pass RAISED past the await -- since
these passes never raised (they returned a normal dict), the escalation
never fired. consolidate therefore reported status: "ok" and
failed_stages: [] while four maintenance passes were silently broken on
the default backend, on every run (GitHub issue #636, reported by
billothewild). The fourth pass (_lesson_promotion_backlog) already
degraded to None on the same AttributeError, but mischaracterized SQLite
as "fallback in tests" in its docstring, and called
silent_failure.note() on every occurrence -- incrementing
cortex_silent_failures_total on every consolidate run for the lifetime of
a SQLite install, for a gap that isn't actually a failure.

Five more consolidation passes not wired into consolidate (one-shot,
manually-invoked CLI campaign scripts: memory_dedup_exact_pass,
memory_domain_backfill_pass, memory_reheat_pass, near_dup_calibration_pass
(two entry points), write_class_backfill_pass) share the exact same
unconditional store.batch_pool access and the exact same
try/except-swallows-into-an-error-status shape, confirmed by reading each
file, not assumed.

ingest_codebase.py's entity/edge ingestion also references
store.batch_pool unconditionally, with no try/except at all, but its
sink's SQL uses PostgreSQL's COPY ... FROM STDIN wire protocol (confirmed
in mcp_server/infrastructure/staging_resolve_sink.py), which has no SQLite
equivalent whatsoever -- this is a materially larger, pre-existing,
PG-only architectural gap (crashes loudly today, not silently), not a
simple missing-guard bug, and is left out of this fix's scope for the
user to decide on separately.

## Decision

Add mcp_server/handlers/consolidation/batch_pool_capability.py, a single
shared batch_pool_skip_reason(store) helper (plain hasattr(store,
"batch_pool"), not a runtime_checkable Protocol -- this guards one
attribute, not a multi-member capability, and
tests_py/handlers/consolidation/test_wiki_citation_seed_pass.py already
established hasattr(store, "batch_pool") as this exact capability's
check). Every one of the nine call sites identified above now checks it
before entering its try block and returns {"status": "skipped: store has
no batch_pool (non-PostgreSQL backend)"} instead of ever reaching
AttributeError. wiki_maintenance.py gained _escalate_if_error(out, key,
result): after each sub-pass call it now also escalates out["status"]
when the returned (not just a raised) status starts with "error:" --
fixing the previously dead escalation path -- while a "skipped: ..."
status, the correct and expected outcome on SQLite, does not escalate.
wiki_backlog_pass._lesson_promotion_backlog now checks the same helper
first and returns None without calling silent_failure.note() when the
capability is simply absent, reserving that call (and its metric) for a
genuine query failure once batch_pool exists; its docstring no longer
calls SQLite a test-only fallback.

ingest_codebase.py's batch_pool usage is explicitly left unfixed here;
flagged for the user as a separate, higher-severity, architecturally
distinct problem.

This branch's ADR was deliberately numbered 1089, not the 1087 the
next-free-number scan would otherwise assign: two sibling branches for
the same reporting session (fix/issue-634-sqlite-vec,
fix/issue-633-backend-marker; GitHub PRs #637, #638) already claimed 1087
and 1088 independently from the same main tip, and both PRs already
document that collision against each other. Picking 1089 here avoids
adding a third branch to that same collision; whichever of the three PRs
merges last still renumbers as needed against whichever of the other two
landed first.

## Consequences

Positive: consolidate's status field and failed_stages now mean what they
say for every batch_pool-gated pass, on both backends -- a SQLite install
sees an honest "skipped: ..." reason per pass instead of a fake "ok", and
a genuine future query failure (once batch_pool exists) still escalates
correctly. cortex_silent_failures_total stops being polluted by an
expected, permanent SQLite condition. The five standalone campaign
scripts get the same honest status instead of an AttributeError disguised
as a generic error string. The fix is mechanical and low-risk: one new
~20-line helper, one guard clause per call site, no behavior change on
the PostgreSQL path.

Negative: SQLite installs still cannot backfill wiki page sources/domains
or reconcile wiki.citations, or recalibrate memory heat/dedup/write-class
via these passes -- this ADR only makes that gap honest, it does not
close it (giving SQLite a real implementation of these Postgres-schema
features is a materially larger effort, correctly deprioritized by the
issue reporter as a separate judgment call). ingest_codebase.py's
COPY-based entity/edge ingestion remains unguarded on SQLite and still
crashes loudly there; this ADR explicitly does not address it. This
branch's ADR-1089 numbering choice depends on 1087/1088 staying claimed
by the two sibling PRs above at merge time -- if either of those PRs is
abandoned instead of merged, 1089 leaves a gap rather than a collision,
which is the safe failure direction.
