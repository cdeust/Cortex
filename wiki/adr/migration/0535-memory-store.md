---
kind: adr
number: 0535
title: Preserve memory_store design decisions
status: accepted
---

# ADR-0535: memory_store design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/memory_store.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
CLI mode: PostgreSQL required, no silent fallback.
Cowork mode: tries PostgreSQL, falls back to SQLite when no DATABASE_URL was
explicitly configured (the DB-less inspection/sandbox contract). When
DATABASE_URL IS explicitly set (env var or constructor arg) and unreachable,
falls back only with CORTEX_ALLOW_SQLITE_FALLBACK=1 opt-in — otherwise raises,
so a misconfigured production DATABASE_URL never silently redirects writes to
a different database. See _database_url_is_explicit for the explicitness test.

````

### get_shared_store, original line 95

````text
    Handlers MUST use this instead of constructing MemoryStore(...) directly:
    each store owns two psycopg pools, so one cached store caps live
    connections regardless of how many of the 37 handlers ask for it. See the
    module-level note on _shared_stores for the CI-hang / quota-leak history.
    
````

### _construct_store, original line 155

````text
    CLI mode: PostgreSQL required (auto → postgresql). Raises on failure.
    Cowork mode: tries PostgreSQL, falls back to SQLite.
    Explicit sqlite backend always works (for testing).
    
````

### _database_url_is_explicit, original line 246

````text
    ``settings.DATABASE_URL`` (memory_config.py) carries a hardcoded default
    (``postgresql://127.0.0.1:5432/cortex``) so it is indistinguishable in
    *value* from a real operator-supplied URL that happens to match it —
    the explicitness test must be on the SOURCE (was a URL supplied at all),
    not the value. Two sources count as explicit, matching the priority
    order in ``_construct_store``/``_resolve_backend_url``:
      1. ``database_url`` passed directly to the constructor (CLI arg, test
         fixture, or caller-supplied override).
      2. The bare ``DATABASE_URL`` env var — the convention this codebase
         uses everywhere else (pg_store.py, doctor.py, session_start.py,
         etc.) to mean "the operator configured Postgres".
    ``CORTEX_MEMORY_DATABASE_URL`` (the pydantic-settings prefixed var
    documented in README.md for the "postgresql"/"auto" backend) is NOT
    checked here: pydantic-settings folds it into ``settings.DATABASE_URL``
    before this function ever sees it, so by the time execution reaches
    here it is already indistinguishable from the hardcoded default. This
    is a known blind spot — an operator using only the prefixed var will
    get the sandbox (silent-fallback-with-warning) behavior instead of the
    strict one. Documented rather than silently "fixed" by inspecting
    pydantic internals, because doing so would require importing the
    settings' env-value provenance, which pydantic-settings does not
    expose. source: this file, _resolve_backend_url and _construct_store
    priority chain (database_url param > os.environ["DATABASE_URL"] >
    settings.DATABASE_URL).
    
````

### MemoryStore, original line 67

````text
        CLI mode: PostgreSQL required (auto → postgresql). Raises on failure.
        Cowork mode: tries PostgreSQL, falls back to SQLite.
        Explicit sqlite backend always works (for testing).
````

### comment, original line 25

````text
# `MemoryStore` is a *factory*: its __new__ (below) returns a fully-built
    # PgMemoryStore or SqliteMemoryStore, never a bare `MemoryStore` instance.
    # For the type checker the public name therefore resolves to the union of
    # the concrete backends the factory can produce, so every
    # `store: MemoryStore` annotation and every `MemoryStore(...)` /
    # `get_shared_store()` result exposes the real store interface instead of
    # an empty factory shell. At runtime the name is the class defined in the
    # `else` branch below (a callable that dispatches to _construct_store).
````

### comment, original line 37

````text
# Process-wide store cache. 37 MCP handlers each used to construct their own
# store via MemoryStore(...), and each store eagerly opens psycopg pools
# (min2/max8 interactive + min1/max2 batch). conftest only reset 5 of them, so
# connections leaked past 60 and the 1800s batch-pool acquire timeout produced
# the 30-minute CI hangs. Caching one store per (backend, url, dim) caps live
# connections at a single store's two pools regardless of handler count, and
# fixes the same connection-quota leak in production.
````

### comment, original line 167

````text
# In CLI mode, "auto" means PostgreSQL is required
````

### comment, original line 181

````text
# Inspection-mode fallback — Glama's sandbox, CI smoke
        # tests, and first-glance experimenters launch Cortex with
        # no DATABASE_URL. Rather than hard-fail and leave them
        # unable to even see the tool surface, drop to SQLite with
        # a loud warning. Real production users who have
        # configured Postgres will see the PG connect succeed;
        # only unset/unreachable installs trip this path.
````

### comment, original line 209

````text
# "auto" in cowork mode: try PG, fall back to SQLite — but only when the
    # URL came from the DB-less inspection default, not from an operator who
    # explicitly configured a target. An explicit DATABASE_URL that fails to
    # connect must not silently redirect writes to a different database
    # (integrity risk: the caller believes it is writing to Postgres).
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.

### _resolve_backend_url: completeness audit

````text
Resolve the (backend, url) a construction would target — the cache key
discriminators. Mirrors the branch selection in _construct_store.
````
