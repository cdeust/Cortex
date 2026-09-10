---
kind: adr
number: 0561
title: Preserve pg_store_query_stream design decisions
status: accepted
---

# ADR-0561: pg_store_query_stream design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pg_store_query_stream.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Split out of pg_store_queries.py (issue #407: 401 lines over the
300-line §4.1 cap) — keyset-paginated and server-side-cursor streaming
reads are their own concern: bounded per-page memory, not a single
filtered SELECT.

````

### _fetch_hot_page, original line 29

````text
        ``last_heat``/``last_id`` None means the first page (no cursor
        yet). Keyset cursor: strictly-after (last_heat, last_id) in the
        (heat_base DESC, id DESC) order — tuple compare is index-friendly
        with the composite ``(heat_base DESC, id DESC)`` index. See
        ``iter_hot_memories_chunked``'s docstring for why this beats a
        server-side cursor over ``ORDER BY heat_base DESC`` here.
        
````

### iter_hot_memories_chunked, original line 59

````text
        Index-backed range scans, NOT a server-side cursor over ``ORDER
        BY heat_base DESC`` (EXPLAIN showed a ~79s upfront sort stall on
        the full table, 2026-06-03). See ``_fetch_hot_page`` for the
        per-page keyset query and the ``columns``/allowlist contract.
        ``hard_limit`` bounds the hottest-N subset (``None`` = full
        corpus); the caller paginates to exhaustion when unset.
        
````

### _stream_decay_cursor_chunks, original line 102

````text
        Uses ``itersize=chunk_size`` on a named cursor so psycopg fetches
        rows from the server in batches rather than buffering all
        results client-side. Batch pool: consolidate is the dominant
        caller; long-lived connection for cursor iteration. The pool is
        autocommit=True, but a named (server-side) cursor needs
        ``DECLARE CURSOR`` inside an open transaction — so the iteration
        wraps in ``conn.transaction()`` (issues BEGIN/COMMIT even under
        autocommit); that also gives the whole stream one consistent
        snapshot. The connection stays borrowed for the duration of
        iteration (the pool's ``with`` is held by the caller via the
        yielded generator lifetime).
        
````

### iter_memories_for_decay, original line 137

````text
        Phase 4: replaces the single ``SELECT *`` that materialized 66K+
        rows (multi-MB per chunk) into Python memory with a chunked
        iterator. Each yielded chunk is a list of normalized memory
        dicts; callers that compute streaming stats (Welford moments
        for homeostatic) can discard each chunk before the next lands.
        See ``_stream_decay_cursor_chunks`` for the pool-enabled path.
````

### iter_memories_for_decay, original line 137

````text
        Source: docs/program/phase-5-pool-admission-design.md (Phase 4
        chunked consolidate).
        
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
