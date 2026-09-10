---
kind: adr
number: 0527
title: Preserve groomer_coordinator design decisions
status: accepted
---

# ADR-0527: groomer_coordinator design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/groomer_coordinator.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Session-counted shared groomer coordinator (issue #171).
````

### module, original line 1

````text
Problem it fixes: ``session_start`` used to spawn the 6-hour consolidate
cycle PER session, gated only by a global ``.last_consolidate`` stamp whose
in-flight marker (``"...T... (in-flight)"``) is *unparseable* by
``read_stamp`` — so a second session opening while the first cycle is in
flight reads the stamp as ``None`` (never-run), judges it stale, and spawns
a DUPLICATE cycle against the same store.
````

### module, original line 1

````text
This replaces that race with a session-counted, per-store coordinator (CBM's
session-coordination semantics, narrowed to Cortex's one-groomer-per-store
need — NOT a general service daemon):
````

### module, original line 1

````text
* **first session ensures the groomer runs** — ``ensure_cycle`` spawns only
  when the period has elapsed AND no cycle is already running.
* **each session registers / deregisters** — ``register`` on SessionStart,
  ``deregister`` on SessionEnd; one liveness-validated file per session.
* **last exit stops it** — ``stop_if_last`` clears the active marker (and
  invokes an injected ``stop_fn``) when the final session deregisters.
* **exactly one cycle per period across N sessions** — the period stamp is
  written UNDER a per-store lock as a *valid parseable* timestamp, so a
  concurrent session that later takes the lock reads it fresh and skips. The
  lock serialises simultaneous decisions; the stamp serialises sequential.
````

### module, original line 1

````text
Crash safety: a ``kill -9``'d session leaks its registration file but not its
liveness — ``live_session_count`` sweeps dead-pid registrations before
counting (mirroring ``session_registry.purge_dead_entries``), and the
single-instance guard is a pid file validated by liveness, never a bare flag.
````

### resolve_store_key, original line 69

````text
Filesystem-safe key identifying the store this coordinator guards.
````

### resolve_store_key, original line 69

````text
    precondition: none. postcondition: returns a stable 16-hex-char token
    derived from the resolved store identity — the SQLite DB path on the
    SQLite backend, the ``DATABASE_URL`` on PostgreSQL — so two windows
    against the SAME store share a coordinator dir and two windows against
    DIFFERENT stores never collide. Degrades to a fixed ``"default"`` key
    (never raises) when backend resolution fails, so coordination still
    happens (one shared coordinator) rather than silently splitting.
    
````

### GroomerCoordinator, original line 99

````text
    Construct with an explicit ``store_key`` (see ``resolve_store_key``);
    ``root`` is overridable for tests. All state lives under
    ``root/<store_key>/``: ``sessions/<pid>.json`` registrations, a
    ``groomer.lock`` decision lock, a ``groomer.pid`` single-instance
    guard, a ``.last_consolidate`` period stamp, and an append-only
    ``runs.log`` (NDJSON) for operational duplicate-run observability.
    
````

### register, original line 123

````text
        postcondition: ``sessions/<session_pid>.json`` exists holding
        ``{v, pid, registered_at}``, written atomically. Returns False
        (never raises) on I/O failure, so the caller can degrade to legacy
        per-session behaviour with a logged NOTICE.
        
````

### deregister, original line 140

````text
Remove a session's registration. Idempotent; never raises.
````

### live_session_count, original line 147

````text
        postcondition: every ``sessions/<pid>.json`` whose ``pid`` is no
        longer alive (crash / kill -9) is unlinked; returns the count of
        the survivors. Never raises — an unreadable dir counts as zero.
        
````

### _iter_session_files, original line 165

````text
Yield ``(path, pid)`` for valid registration files. Never raises.
````

### is_groomer_running, original line 181

````text
True iff ``groomer.pid`` names a live process (liveness-validated,
        not a bare flag). A stale pid file from a crashed cycle names a dead
        pid and reads as not-running. Never raises.
````

### ensure_cycle, original line 195

````text
Ensure at most one grooming cycle runs per ``period_hours``.
````

### ensure_cycle, original line 195

````text
        precondition: ``spawn_fn()`` starts the consolidate cycle and
        returns its pid (or None). postcondition: returns exactly one of
        ``STARTED`` / ``SKIPPED_FRESH`` / ``SKIPPED_RUNNING`` /
        ``SKIPPED_LOCKED``. ``spawn_fn`` is called AT MOST once, and only on
        ``STARTED``. Under the per-store lock the period stamp is (re)written
        as a valid ISO timestamp BEFORE spawning, so any concurrent session
        that subsequently takes the lock observes a fresh stamp and returns
        ``SKIPPED_FRESH`` — the invariant guaranteeing one cycle per period
        across N sessions. invariant: no path both writes the stamp and
        returns a SKIPPED_*.
        
````

### stop_if_last, original line 235

````text
        postcondition: the session's registration is removed; when no live
        session remains, the ``groomer.pid`` single-instance marker is
        cleared and ``stop_fn`` (if given) is invoked. Returns True iff the
        stop path fired (this was the last session). Never raises.
        
````

### count_cycles_since, original line 260

````text
Number of ``STARTED`` cycles logged at/after ``since``.
````

### count_cycles_since, original line 260

````text
        Operational evidence for the issue's "zero duplicated consolidate
        runs over 24h" criterion: with coordination working, this returns at
        most one per period window. Never raises — a missing/corrupt log line
        is skipped, not fatal.
        
````

### comment, original line 57

````text
# Outcomes of ``ensure_cycle`` — a small closed set of strings so callers
# and tests can branch/observe without importing an Enum across the
# boundary. source: design #171 (this module).
````

### comment, original line 63

````text
# another session holds the decision lock right now
````

### comment, original line 83

````text
# str(...) coercion: MemorySettings is a pydantic BaseSettings whose
        # attributes the type checker resolves as Unknown; these values ARE
        # strings, and coercing makes ``identity`` a definite ``str`` (never
        # ``str | None``) so the hash below is well-typed. ``get(k) or dflt``
        # (not ``get(k, dflt)``) keeps the same narrowing for the env case.
````

### comment, original line 178

````text
# ── single-instance guard ───────────────────────────────────────────
````

### comment, original line 218

````text
# Commit the period BEFORE spawning: the stamp is the barrier.
````

### comment, original line 257

````text
# ── observability (24h zero-duplication evidence) ───────────────────
````

### comment, original line 310

````text
# Valid ISO only — NEVER an unparseable "(in-flight)" suffix (that
        # was exactly the #171 duplication bug: read-back returned None →
        # concurrent re-spawn). source: design #171 (this module).
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
