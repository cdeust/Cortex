---
kind: adr
number: 0508
title: Preserve capture_client design decisions
status: accepted
---

# ADR-0508: capture_client design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/capture_client.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Ensure one worker and admit one capture, without loading inference code.
````

### deliver, original line 42

````text
Return after admission; uncertain delivery raises and is never replayed.
````

### comment, original line 18

````text
# Serialize inspection with bind/chmod/listen, including warm connections.
    # A socket pathname exists before its owner-only permissions are ready.
````

### comment, original line 24

````text
# Absence before sending is the only safe restart point.
````

### comment, original line 31

````text
# An exiting worker may already have closed its listener while closing stores.
    # Wait within the same budget so normal teardown does not drop the next capture.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
