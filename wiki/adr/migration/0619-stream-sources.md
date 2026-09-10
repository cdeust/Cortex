---
kind: adr
number: 0619
title: Preserve stream_sources design decisions
status: accepted
---

# ADR-0619: stream_sources design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/stream_sources.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Wraps an existing keyset / named-cursor iterator (``iter_hot_memories_chunked``,
``iter_memories_for_decay``, or any ``(chunk_size) -> Iterator[list]`` factory)
as a ``StreamSource``. These iterators already stream at a measured 74MB peak
RSS / ~49.5k rows/s on a 500k-row corpus — the proven primitive; this adapter
only re-exposes them under the pipeline's port.
````

### CursorStreamSource, original line 22

````text
    The factory MUST use keyset or server-side-cursor pagination (value-anchored
    boundaries), never OFFSET — OFFSET drifts under concurrent mutation.
    
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
