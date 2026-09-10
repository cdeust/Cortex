---
kind: adr
number: 0510
title: Preserve capture_peer design decisions
status: accepted
---

# ADR-0510: capture_peer design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/capture_peer.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### comment, original line 26

````text
# source: unix(7), struct ucred = pid_t, uid_t, gid_t.
````

### comment, original line 32

````text
# source: Apple getpeereid(3); uid_t/gid_t are unsigned int on macOS.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
