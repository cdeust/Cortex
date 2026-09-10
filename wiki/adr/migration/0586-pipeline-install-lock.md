---
kind: adr
number: 0586
title: Preserve pipeline_install_lock design decisions
status: accepted
---

# ADR-0586: pipeline_install_lock design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pipeline_install_lock.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Prevents concurrent setup.sh runs (or a SessionStart auto-install racing
the user's manual setup) from corrupting the shared install state:
half-cloned src/, racy symlink swap, JSON config truncation.
````

### module, original line 1

````text
Non-blocking acquire — contended runs return immediately so callers can
surface a clear ``install_in_progress`` action rather than hanging the
user's terminal for 6 minutes.
````

### module, original line 1

````text
POSIX uses ``fcntl.flock`` (advisory lock). Windows has no ``fcntl`` — its
import alone would crash this module at load on every Windows install — so
we use ``msvcrt.locking`` (mandatory byte-range lock) there. Both back the
same ``install_lock()`` contract; the only visible difference (advisory vs
mandatory) is immaterial because every caller goes through this function.
````

### module, original line 1

````text
source: RAPPORT_INSTALLATION_CORTEX_WINDOWS.md §5.4

````

### install_lock, original line 38

````text
    Raises ``InstallLockBusyError`` immediately on contention so callers can
    return a structured ``install_in_progress`` action instead of
    blocking for the duration of someone else's 6-minute build.
````

### install_lock, original line 38

````text
    We never read or write content — only the lock metadata matters. The fd
    stays open for the duration of the context to keep the lock held.
    
````

### comment, original line 63

````text
# == shared.platform.IS_WINDOWS; literal so the checker
````

### comment, original line 64

````text
# resolves the msvcrt/fcntl split per-platform instead of flagging both.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.

### install_lock: completeness audit

````text
Acquire an exclusive non-blocking lock on the install file.

Raises ``InstallLockBusyError`` immediately on contention so callers can
    return a structured ``install_in_progress`` action instead of
    blocking for the duration of someone else's 6-minute build.

source: ADR-0586
````
