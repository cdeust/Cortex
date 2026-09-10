---
kind: adr
number: 0545
title: Preserve pg_store_ddl design decisions
status: accepted
---

# ADR-0545: pg_store_ddl design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pg_store_ddl.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Split out of pg_store.py (issue: 1384-line file over the 300-line §4.1
cap) — this module owns ``_execute`` (the pooled query entrypoint every
other mixin calls) and schema migration (``_init_schema``, gated on a
content hash of the DDL set). Connection/pool plumbing lives in the
sibling ``pg_store_schema`` module.
````

### compute_ddl_hash, original line 41

````text
    Pre: none. Post: deterministic hex digest — same algorithm and input
    order as ``PgMemoryStore._init_schema``'s migration gate, so external
    callers (e.g. ``mcp_server.migrate``, a standalone entry point that
    must decide "is the DB current" without constructing a full store
    first) compute the identical value. Single source of truth: both
    ``_init_schema`` and this function call ``get_all_ddl()``, never a
    duplicated statement list.
    
````

### read_schema_hash, original line 55

````text
    Pre: ``conn`` is a live psycopg connection opened with
    ``row_factory=dict_row`` (matches every connection this module opens —
    ``PgMemoryStore._create_connection`` and standalone probes alike).
    Post: returns the hash of the last-applied DDL revision, or None when
    ``schema_meta`` doesn't exist yet (fresh DB) or the read fails for any
    reason — both cases mean "not yet migrated to any known revision".
    Read-only; issues no DDL and leaves no aborted-transaction state
    behind on failure.
    
````

### _get_database_url, original line 74

````text
    An unexpanded ``${user_config.database_url}`` token (Claude Code passes the
    literal through if the user_config option is unset and carries no default)
    is treated as unset, so the settings default still applies.
    
````

### _execute, original line 92

````text
        Phase 5: borrows a connection from ``interactive_pool`` for each
        call so concurrent ``asyncio.to_thread`` workers are safe. Because
        the returned cursor's ``fetch*`` must complete before the
        connection is returned to the pool, we read all rows eagerly
        into an in-memory cursor surrogate.
````

### _execute, original line 92

````text
        On 'cached plan must not change result type' (FeatureNotSupported):
        deallocates all prepared statements on the pool connection and
        retries once.
        On connection errors: recycles the pool connection and retries.
````

### _recorded_schema_hash, original line 174

````text
        A missing ``schema_meta`` table (fresh DB) or any read error reads
        as None → the caller migrates. Single-row indexed lookup; no
        table scan, no locks. ``self._conn`` is autocommit, so a failed
        read leaves no aborted-transaction state behind. Delegates to the
        module-level ``read_schema_hash`` — see that function for the
        single source of truth shared with standalone callers.
        
````

### _init_schema, original line 197

````text
        Migration is gated on a content hash of the full DDL set
        (``get_all_ddl()``, a deterministic fixed-order list), recorded in
        ``schema_meta``. On an already-provisioned DB whose recorded hash
        matches the code, this is a single indexed SELECT — no advisory
        lock, no DDL re-application. DDL runs only when the hash differs
        (a fresh DB, or a code change to the schema), serialized under the
        advisory lock with a double-check so concurrent first-time inits
        don't re-run it. See ``_apply_ddl_locked`` for what happens once
        the lock is held.
````

### _init_schema, original line 197

````text
        Root-cause fix for the connection storm: the 47 ``MemoryStore``
        construction sites previously each re-ran 83 DDL statements while
        HOLDING a connection on ``pg_advisory_lock``, piling dozens of
        sessions onto one lock until ``max_connections`` was exhausted.
        Recording the applied revision decouples migration from
        construction: once the DB is current, construction touches no
        lock and no DDL.
````

### _apply_ddl_locked, original line 233

````text
        Blocking is correct here because it is RARE (only on a genuine
        schema change), so dozens of inits cannot stack up on it the way
        per-construction DDL did. Always releases the lock (finally),
        even if a peer already applied the revision while we waited or a
        statement failed.
        
````

### has_vec, original line 268

````text
Always true — pgvector is mandatory.
````

### comment, original line 34

````text
# Explicit name (not __name__): _execute_on_conn/_init_schema log under the
# pg_store.py facade's logger namespace, unchanged by the module split —
# preserves observable log output for any external log-name filter.
````

### comment, original line 128

````text
# Single trust boundary for psycopg's LiteralString query typing:
        # every str reaching here is either a module literal or an
        # allowlist-gated build whose mechanism its site names under the
        # ruff S608 gate (docs/ASSURANCE-CASE.md §5) — values always travel
        # separately as bound params.
````

### comment, original line 154

````text
# Advisory lock id for schema bootstrap. Two processes hitting a
    # fresh DB simultaneously (e.g. http_standalone + a worker subproc)
    # used to deadlock on the A3 migration's ALTER TABLE / CREATE INDEX
    # pair. With this lock, the second process waits for the first to
    # finish before re-running idempotent DDL.
    # source: hashlib.sha256(b'cortex_schema_a3').hexdigest() mod 2**31
````

### comment, original line 162

````text
# One-row table recording the content hash of the LAST-APPLIED DDL
    # set. Construction re-applies DDL only when the code's hash differs
    # from this — see ``_init_schema``. Created lazily by the first
    # migration so a fresh DB bootstraps cleanly.
````

### comment, original line 225

````text
# Fast path: DB already at this exact DDL revision. This is the
        # steady state for every construction once the DB is provisioned —
        # no lock, no DDL, so no pile-up can form.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
