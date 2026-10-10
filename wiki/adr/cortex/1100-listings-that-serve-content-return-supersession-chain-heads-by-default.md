---
created: 2026-10-10T07:04:31Z
kind: adr
number: 1100
status: accepted
tags: [memory, supersession, listings, issue-687]
title: Listings that serve content return supersession chain heads by default
---
# ADR-1100: Listings that serve content return supersession chain heads by default

## Status

accepted

## Context

Issue #687: after `remember(..., supersedes_id=<old>, force=True)` created a new row, `query_methodology` returned both rows in `hotMemories`, and the old row still carried a statement its owner had withdrawn. The `remember` tool says recall demotes the superseded version. Root cause: the shared listing primitives (`get_hot_memories`, `get_memories_for_directory` and the others) defaulted to `heads_only=False` and every content-serving caller had to opt in; `query_methodology`, the narrative and project-story tools, `sync_instructions`, `checkpoint`, `assess_coverage` and `detect_gaps` did not, `curate_wiki` and `curate_distill` fell back to `get_recent_memories`, which read the whole table, and `get_memories_by_tag`, `get_recent_memories` and `get_memories_for_directory` had no heads option at all.

The earlier read-path audit (`docs/program/pr2-read-path-supersession-audit.json`, cited by ADR-0258, ADR-0537, ADR-0602 and ADR-1014 and by several tests) recorded the opposite default: content-serving callers pass `heads_only=True`, `validate_memory` stays on the physical chain. That default made the safe behaviour opt-in, and the defect is the callers that forgot.

## Decision

1. A head is a memory whose `superseded_by_id` is NULL. Both backends expose it as the view `current_memories` (`sqlite_schema.py` and `pg_schema.py`, defined the same way).
2. Every listing primitive that serves memory content, or a count shown to a user, returns heads by default: `heads_only=True` is the default of the five shared primitives on SQLite and PostgreSQL, and `get_memories_by_tag`, `get_recent_memories` and the `wiki_extract` candidate selection read `current_memories`. `get_memories_by_tag`, `get_memories_for_entity` and `get_all_memories_for_validation` take `heads_only` and default to True on both backends. Callers that read the store directly or pass it explicitly are heads-only: the SessionStart pending-curation count and cached-graph-path lookup (`session_start.py`, via `current_memories`), the post-store boost and entity listing (`write_post_store.py`, `heads_only=True`), the memify provenance lookup (`get_memories_for_entity`, `heads_only=True`), and the `assess_coverage` and `change_impact` scans. This reverses the default recorded in `docs/program/pr2-read-path-supersession-audit.json` and supersedes that document, which is updated to say so.
3. Readers that need the physical chain are maintenance and pass `heads_only=False` explicitly: `validate_memory` (all three selection paths), the pruning, plasticity and `memory_staleness_pass` passes, and the idempotency and duplicate-prevention lookups: memify's `derived-rel` scan and curate_distill's `distill-of` scan (both read `get_memories_by_tag`), `find_existing_memory` in `ingest_findings_writers.py` and `already_ingested` in `ingest_document_writers.py`, which must still see a superseded carrier so a corrected fact is not derived twice and a retracted text is not written back as a fresh head. The list is pinned by a test that derives the listing set from the store signatures and requires the same set on both backends.
4. Deliberate exceptions, which read the physical rows: `search_vectors` (the vector index is keyed by physical rows), the consolidation readers, lookups by id, and the history, audit and chain tools that read by id or through the recursive chain query. Two helpers without a caller (`get_memories_created_after`, `get_memories_in_time_window`) are not changed.
5. A listing of N rows returns N heads when more than N exist: the head filter is part of the view and applies before ordering and the limit.
6. Not decided here and tracked as defects: deleting the head of a chain behaves differently on the two backends (PostgreSQL clears `superseded_by_id` through `ON DELETE SET NULL` so the previous version resurfaces; SQLite leaves a dangling pointer so the whole chain disappears from default listings: issue #699); `query_methodology._get_hot_memories` swallows an exception and returns an empty list (issue #685); `memory_stats.total` and the SessionStart banner total count every stored row, retracted versions included, as a storage figure, and are not changed here.

## Consequences

Positive: a withdrawn statement can no longer be served to a session through a listing, because the safe behaviour is the default and a maintenance reader has to ask for the physical chain in a way a test can audit. Negative and known limits: the default flip changes every caller that passed nothing, so a reader that must see superseded rows has to say so (the pin test sees only a literal `heads_only=False` on any store listing with a `heads_only` parameter, and requires an explicit `heads_only` on every listing call in `handlers/consolidation/` and `validate_memory.py`; it cannot see a computed value or a maintenance caller in an unlisted module; a store whose `get_memories_for_entity` lacks the keyword makes memify's provenance lookup fall into `silent_failure` and return empty, so five test fakes needed the keyword); the SQLite and PostgreSQL divergence on deleting a head is widened by head-only defaults until issue #699 is fixed; the partial index `idx_memories_superseded_by` does not serve the `IS NULL` predicate of the view, so the cost on a large table is unmeasured; this amends ADR-0258, ADR-0537, ADR-0602 and ADR-1014 where they cite the old default.
