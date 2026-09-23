---
created: 2026-09-23T00:00:00Z
kind: adr
number: 1090
status: accepted
tags: [consolidate, sqlite, wiki, issue-636]
title: Gate PG-only wiki passes once at wiring time instead of catching their AttributeError
---
# ADR-1090: Gate PG-only wiki passes once at wiring time instead of catching their AttributeError

## Status

accepted

## Context

consolidate's wiki maintenance cycle runs four passes on every invocation --
wiki_source_backfill_pass, wiki_domain_backfill_pass, wiki_citation_seed_pass,
and wiki_backlog_pass's lesson-promotion count -- each of which needs
store.batch_pool, a psycopg_pool.ConnectionPool that only PgMemoryStore
provides, because the SQL they run is Postgres-schema-qualified
(wiki.pages, wiki.citations, %s placeholders) with no SQLite equivalent.
SqliteMemoryStore, the zero-config default backend, has no batch_pool
attribute at all, so every one of these passes raised AttributeError on
every SQLite install, on every run.

Three of the four passes already caught that AttributeError internally
and returned {"status": "error: ..."} instead of letting it propagate.
wiki_maintenance.py's own escalation logic only bumped out["status"]
away from "ok" when a sub-pass RAISED past the await -- since these
passes never raised, the escalation never fired. consolidate therefore
reported status: "ok" and failed_stages: [] while four maintenance
passes were silently broken on the default backend, on every run
(GitHub issue #636, reported by billothewild, a non-developer end user
running Cortex on Windows).

A first version of this fix added a hasattr(store, "batch_pool") guard
inside each of the nine affected call sites (the four consolidate-wired
passes plus five standalone campaign scripts sharing the identical
pattern), turning the AttributeError into a returned {"status": "skipped:
..."} stanza. The owner rejected that design on review: it is the same
shape of problem restated with a softer word -- a runtime catch papering
over a wiring defect, not a fix at the root. The repo's own non-negotiable
already said so: "no silent fallbacks or compatibility shims." A PG-only
pass handed a SQLite store is a programming error, not a degraded runtime
condition, and should never be reachable in the first place.

## Decision

Decide once, at the top of run_wiki_maintenance, whether store is
PostgreSQL-backed (hasattr(store, "batch_pool") -- the same idiom this
file already used for iter_memories_for_decay). Only invoke
run_source_backfill_pass, run_domain_backfill_pass,
run_wiki_citation_seed_pass, and wiki_backlog_pass._lesson_promotion_backlog
inside that branch. On a non-PostgreSQL store, these four keys are
absent from the response entirely -- not reported as failed, not reported
as skipped, simply not part of the shape a SQLite user's consolidate
response has, the same way "wiki" itself is absent from consolidate's
top-level stats when the wiki=False flag is passed.

The four passes themselves no longer catch their own AttributeError (or
any exception) for the "no batch_pool" case: run_wiki_maintenance is each
one's sole caller, and calling one without batch_pool is now a wiring
bug that surfaces as AttributeError, exactly like any other broken
precondition. Removing the passes' internal try/except also makes
run_wiki_maintenance's existing except blocks around each await the
single, live error boundary for a genuine failure (a real query error on
a store that does have batch_pool) -- those blocks had been dead code
for the "wrong backend" case since the passes swallowed it themselves
before this fix.

wiki_backlog_pass._lesson_promotion_backlog moves out of run_backlog_pass
(which runs unconditionally, since its other counts are filesystem-based
and backend-agnostic) into run_wiki_maintenance's own PostgreSQL branch.
Its own internal try/except is also removed, matching the other three
passes: it now raises on a genuine query failure instead of degrading to
a silent None, and run_wiki_maintenance wraps the call in its own
try/except, escalating out["status"] to
"lesson_promotion_backlog_error: ..." the same way it does for the other
three. An earlier version of this same commit kept the swallow in place
-- reviewed and corrected before landing, since None with status still
"ok" is the exact shape #636 reported, just for one key instead of four.
This also removes the silent_failure.note call that previously fired --
and incremented cortex_silent_failures_total -- on every consolidate run
for the lifetime of a SQLite install; the wiring change alone (this
function is never called at all on a non-PostgreSQL store) already made
that metric-pollution problem moot.

The five standalone campaign scripts (memory_dedup_exact_pass,
memory_domain_backfill_pass, memory_reheat_pass,
near_dup_calibration_pass's two entry points, write_class_backfill_pass)
are not wired into consolidate and are invoked directly by a human
running the matching scripts/*.py CLI. Their passes keep their original,
pre-#636 try/except (catch a real query failure, return {"status": "error:
..."}) unchanged -- that predates this issue and is the operator-visible
contract for a manually-run campaign, not the silent-inside-consolidate
failure #636 reports. Each script's entry point now checks
hasattr(store, "batch_pool") once, before calling its pass, and exits 1
with a one-line message when absent, instead of the pass discovering the
same fact nine lines deeper.

ingest_codebase.py's entity/edge ingestion also references store.batch_pool
unconditionally, with no try/except at all, but its sink SQL uses
PostgreSQL's COPY ... FROM STDIN wire protocol
(mcp_server/infrastructure/staging_resolve_sink.py), which has no SQLite
equivalent whatsoever. This is a materially larger, pre-existing,
PG-only architectural gap (crashes loudly today, not silently), not a
missing-guard bug, and stays out of this fix's scope for the owner to
decide on separately.

## Consequences

Positive: consolidate's response shape now tells the truth about the
backend it ran against -- a PostgreSQL store gets four extra stanzas
with real data or a real, escalated error; a SQLite store gets none of
them, and status stays "ok" because nothing on that backend actually
failed. A genuine future query failure on the PostgreSQL path still
escalates correctly, since it now reaches the same except blocks a
raised AttributeError always would have. cortex_silent_failures_total
stops recording an expected, permanent SQLite condition. The five
standalone campaign scripts fail fast and legibly instead of returning
a status string 5000 rows into a --apply run.

Negative: any caller (test, script, external integration) that assumed
source_backfill / domain_backfill / citation_seed /
lesson_promotion_backlog were always present in run_wiki_maintenance's
return dict must now branch on their presence. consolidate's own tool
schema documents this (the wiki flag's description). SQLite installs
still cannot backfill wiki page sources/domains or reconcile
wiki.citations, or recalibrate memory heat/dedup/write-class via these
passes -- this ADR makes that gap architecturally explicit, it does not
close it; giving SQLite a real implementation of these Postgres-schema
features is a materially larger effort the issue reporter's own list
correctly deprioritized as a separate judgment call.
