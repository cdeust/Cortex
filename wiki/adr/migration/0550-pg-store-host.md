---
kind: adr
number: 0550
title: Preserve pg_store_host design decisions
status: accepted
---

# ADR-0550: pg_store_host design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pg_store_host.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Typed host contract + materialized cursor for the PostgreSQL store mixins.
````

### module, original line 1

````text
``PgMemoryStore`` is assembled from a family of persistence mixins (issue:
split from a 1384-line pg_store.py over the 300-line §4.1 cap), each of
which calls back into shared machinery the composed class provides
(``_execute``, ``_conn``, ``batch_pool``, ``interactive_pool``, ...).
Before this module existed that contract was implicit — every mixin
accessed ``self._execute`` with no declaration, so the type checker could
not verify a single call against the real signature, and a wrong call (or
a renamed host method) surfaced at runtime instead of in CI.
````

### module, original line 1

````text
``PgStoreHost`` makes the contract explicit: mixins inherit it, the
declarations live under ``TYPE_CHECKING`` so the class is empty at runtime
(zero MRO behavior change), and ``PgMemoryStore`` remains the sole runtime
implementer. This is the DIP form §5.1 of the coding standard asks for: the
mixins (consumers) name the abstraction they need; the store supplies it.
````

### module, original line 1

````text
``MaterializedCursor`` lives here (moved from ``pg_store.py``) so both the
host contract and the store can name the concrete return type of ``_execute``
without an import cycle. Its rows are ``DictRow`` — every connection this
backend opens uses ``row_factory=dict_row`` — which is what lets the type
checker verify ``row["column"]`` access in the mixins.

````

### MaterializedCursor, original line 61

````text
    Phase 5: connections are checked out from the pool per query and
    returned at the end of ``_execute``. The original ``psycopg.Cursor``
    becomes unusable once the connection is returned to the pool, so we
    eagerly read all rows into memory here and expose the subset of the
    Cursor API that production code actually uses: ``fetchone``,
    ``fetchall``, and ``rowcount``.
    
````

### PgStoreHost, original line 120

````text
Static contract every ``Pg*Mixin`` relies on.
````

### PgStoreHost, original line 120

````text
    Declaration-only: the ``TYPE_CHECKING`` guard keeps the class empty at
    runtime, so inheriting it changes no MRO lookup and adds no behavior.
    ``PgMemoryStore`` provides every member listed here.
    
````

### one, original line 90

````text
        For statements whose contract guarantees a row (``INSERT ...
        RETURNING``, aggregate ``SELECT count(*)``). A missing row there
        means the database broke its side of the contract, so this raises
        immediately with the real cause instead of letting the caller fail
        later on a ``None`` with no context.
        
````

### comment, original line 29

````text
# This module is reachable by import from the SQLite-default install (hooks ->
# injection_receipts -> pg_store_receipts -> here), and psycopg ships only in
# the optional [postgresql] extra. A module-scope `import psycopg` therefore
# made `import mcp_server.hooks.session_lifecycle` raise ModuleNotFoundError on
# every launch surface in PRIVACY.md lines 26-38. Only ProgrammingError is
# needed at RUNTIME (the rest are annotations, stringified by
# `from __future__ import annotations`), so the PG-only paths that raise it are
# unreachable without psycopg and the stand-in below is never matched.
# Surfaced by #220 broadening the SQLite CI job to the full suite.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
