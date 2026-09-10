---
kind: adr
number: 0509
title: Preserve capture_lock design decisions
status: accepted
---

# ADR-0509: capture_lock design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/capture_lock.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
The daemon waiter owns a duplicate descriptor: timeout never closes a descriptor
under a blocked flock call. Cancellation makes it release any later acquisition.
Source: Python concurrent.futures.Future cancellation contract; flock(2).

````

### comment, original line 45

````text
# FutureTimeoutError became a builtin TimeoutError alias only in Python 3.11.
    # remaining() can also expire before Future.result() starts waiting.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
