---
kind: adr
number: 0513
title: Preserve capture_transport design decisions
status: accepted
---

# ADR-0513: capture_transport design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/capture_transport.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### comment, original line 11

````text
# source: Python struct docs: !I is a network-order unsigned 32-bit length.
````

### comment, original line 13

````text
# source: capture-worker-design.md, binary admission result.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
