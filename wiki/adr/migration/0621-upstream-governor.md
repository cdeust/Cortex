---
kind: adr
number: 0621
title: Preserve upstream_governor design decisions
status: accepted
---

# ADR-0621: upstream_governor design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/upstream_governor.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Why
---
Upstream MCP servers (e.g. the ``ai-architect-mcp-codebase`` Rust binary behind
the ``codebase`` server) are **single OS processes**. Two Cortex handlers
that each pass admission under *different* per-tool semaphores
(``ingest_codebase`` and ``codebase_analyze`` are distinct names, each
``Semaphore(1)`` — see handlers/admission.py) can still issue heavy
``query_graph`` / ``analyze_codebase`` calls to the **same** child at the
same time. Back-to-back heavy graph queries with no breathing room drive
the child's RSS up until the OS kills it; the next stdin write then raises
``ConnectionResetError: Connection lost``. source: ingest_codebase
ConnectionResetError RCA 2026-06-09.
````

### module, original line 1

````text
This governor serialises (or bounds) calls **per upstream server name**,
across every Cortex handler, so the shared child is never asked to serve
more concurrent work than it can hold.
````

### module, original line 1

````text
Design
------
* Keyed by upstream server name, NOT by tool — the constraint is the child
  process, which is shared across tools.
* Backed by ``threading.Semaphore``, NOT ``asyncio.Semaphore``: batch
  handlers run their coroutine on a fresh per-call event loop in a worker
  thread (tool_error_handler._run_coroutine_on_thread), so an asyncio
  primitive created on one loop and awaited on another raises
  "bound to a different event loop". A threading.Semaphore is loop-agnostic
  and process-global; the blocking acquire is offloaded via
  ``asyncio.to_thread`` so the calling loop stays responsive.
* Default permit count is 1 — full serialisation of the single-process
  child, mirroring admission's batch-class ``Semaphore(1)`` (a single heavy
  writer at a time). Override per server in mcp-connections.json via
  ``maxConcurrentCalls``. source: Kleinrock (1975) bounded-buffer M/M/c/K —
  c is a property of the served resource (here, one process).

````

### _get_semaphore, original line 87

````text
    The first caller's ``max_concurrent`` fixes the budget; later callers
    reuse it (the budget is a property of the served child, not the call).
    
````

### comment, original line 47

````text
# Permits per upstream server when the config does not specify
# ``maxConcurrentCalls``. 1 = serialise (the conservative default for a
# single-process child). source: admission.py batch class Semaphore(1).
````

### comment, original line 52

````text
# Dedicated executor for the blocking ``sem.acquire()`` wait below —
# deliberately NOT ``asyncio.to_thread`` (the process-wide default
# executor, bounded at ``min(32, os.cpu_count() + 4)`` workers per the
# threading module docs). EVERY Cortex tool call also routes through that
# same default executor (tool_error_handler.py's ``_run_coroutine_on_thread``
# / handler dispatch). Now that a governed call may legitimately hold its
# permit for hours (``callTimeoutMs: 0`` — this PR removes the wall-clock
# cap on live ingestion), a handful of callers queued waiting on a busy or
# stuck permit would each pin one default-executor thread for that same
# duration; once queued waiters exceed the pool's worker count, every
# OTHER tool call in the process — including calls to entirely different,
# healthy upstream servers — queues behind them and the whole MCP server
# stops responding. A small dedicated pool isolates that resource: an
# exhausted wait queue here can only starve other governed-call waiters
# for the SAME server, never any other tool. Sized well above the
# realistic number of concurrent waiters for a single local MCP server
# process (one interactive session, a handful of governed upstream
# servers) without being unbounded. source: review round 2 finding P4;
# ThreadPoolExecutor default sizing — CPython `concurrent.futures` docs.
````

### comment, original line 77

````text
# Process-global registry. ``threading.Semaphore`` is thread-safe and
# loop-agnostic, so one instance per server name is shared correctly across
# the worker-thread event loops that batch handlers run on. The dict itself
# is guarded by ``_registry_lock`` for first-use creation.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
