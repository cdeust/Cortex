---
kind: adr
number: 0512
title: Preserve capture_socket design decisions
status: accepted
---

# ADR-0512: capture_socket design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/capture_socket.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Source: capture-worker-design.md; Python os.open/O_NOFOLLOW and flock(2).
Only same-UID processes are trusted. No symlink component is traversed.

````

### comment, original line 23

````text
# source: W3-1c contract (0600 socket), Unix owner-only directories/locks.
````

### comment, original line 25

````text
# source: Unix owner read/write/search only; capture-worker-design.md trust boundary.
````

### comment, original line 80

````text
# Do not LOCK_UN: an inherited descriptor keeps the worker's lease alive.
````

### comment, original line 111

````text
# source: Python socket.listen default kernel backlog.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
