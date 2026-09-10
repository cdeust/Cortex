---
kind: adr
number: 0529
title: Preserve hook_cascade_counter design decisions
status: accepted
---

# ADR-0529: hook_cascade_counter design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/hook_cascade_counter.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
All tool events count, including tools whose content is not captured. A
stable counter lock protects atomic JSON replacements. A separate,
non-blocking execution lock per Claude root serializes hook cascades without blocking
counter writers. Contention/failure leaves due work for a later event.
````

### module, original line 1

````text
This is best effort, not exactly once: a crash after DB advancement but
before its acknowledgement can repeat advancement. It never resets due
work merely because another hook is executing a cascade. One invocation
attempts at most one pending interval, keeping catch-up work bounded.

````

### _session_directory, original line 34

````text
    source: injection_receipts.session_id_from_transcript, decision 4255039
    correction 7 (148/200 fixture lines had a divergent event session_id).
    Do not import that handler here: it eagerly imports the PG stack.
    
````

### comment, original line 28

````text
# source: post_tool_capture.py at 5de4f4a4; existing cadence preserved,
# empirical tuning provenance was not recorded at introduction.
````

### comment, original line 45

````text
# Digest the identity, never interpret an external stem as a state path.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
