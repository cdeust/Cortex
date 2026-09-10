---
kind: adr
number: 0530
title: Preserve hook_counter_lock design decisions
status: accepted
---

# ADR-0530: hook_counter_lock design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/hook_counter_lock.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Like pipeline_install_lock, the lock is separate from replaceable JSON.
Acquisition waits only for a filesystem counter transaction; callers must
never run models, DB operations, or the cascade while holding it.
````

### module, original line 1

````text
source: https://docs.python.org/3/library/fcntl.html#fcntl.flock
source: https://docs.python.org/3/library/msvcrt.html#msvcrt.locking
Windows LK_LOCK uses the CRT's documented retry policy; errors propagate.

````

### comment, original line 25

````text
# source: POSIX owner read/write bits; no session-state access for peers.
````

### comment, original line 41

````text
# source: msvcrt locks a byte range, including beyond end of file.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
