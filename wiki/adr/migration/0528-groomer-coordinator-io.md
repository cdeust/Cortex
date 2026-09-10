---
kind: adr
number: 0528
title: Preserve groomer_coordinator_io design decisions
status: accepted
---

# ADR-0528: groomer_coordinator_io design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/groomer_coordinator_io.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Low-level I/O + lock primitives for the groomer coordinator (issue #171).
````

### module, original line 1

````text
Mechanism half of the policy/mechanism split (coding-standards §1.1 SRP):
``groomer_coordinator.py`` owns the session-counting POLICY; this module
owns the filesystem + cross-platform locking MECHANISM it stands on —
pid-liveness, atomic replace, ISO parsing, and a non-blocking per-store
lock. Kept separate so the policy file reasons about coordination without
carrying the platform ``fcntl``/``msvcrt`` split inline.
````

### pid_alive, original line 24

````text
True iff ``pid`` currently names a live process. Never raises.
````

### pid_alive, original line 24

````text
    A ``PermissionError`` (pid exists, owned by another user) counts as
    alive — same discipline as ``session_registry._pid_alive`` (a peer infra
    module); duplicated rather than importing a private symbol.
    
````

### parse_iso, original line 44

````text
Parse an ISO-8601 stamp to an aware UTC datetime, or None. Never raises.
````

### atomic_write_text, original line 55

````text
    postcondition: a concurrent reader observes either the old content or
    the new content in full, never a torn write. Returns False (never
    raises) on any I/O failure.
    
````

### DecisionLock, original line 82

````text
    ``with DecisionLock(path) as acquired:`` yields True when this holder
    won the lock and False when another holder already owns it (contended
    simultaneous decision). Advisory ``flock`` on POSIX, mandatory
    ``msvcrt.locking`` on Windows — same split as ``pipeline_install_lock``
    (source: RAPPORT_INSTALLATION_CORTEX_WINDOWS.md §5.4). Never raises out
    of ``__enter__``: a lock-open failure degrades to "not acquired" so the
    caller skips rather than crashes.
    
````

### comment, original line 121

````text
# Direct ``sys.platform`` comparison (not the ``IS_WINDOWS`` alias): the type
# checker statically prunes the unreachable branch per its configured target
# platform, so ``msvcrt``/``fcntl`` are each only analysed where they exist —
# an imported bool alias would not enable that narrowing.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
