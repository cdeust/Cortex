---
kind: adr
number: 0526
title: Preserve file_io design decisions
status: accepted
---

# ADR-0526: file_io design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/file_io.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
- read_json returns parsed object or None (never throws)
- write_json creates parent directories as needed
- All text operations use UTF-8 encoding

````

### write_json, original line 29

````text
    Atomic: writes to a sibling temp file in the same directory, then
    ``os.replace``s it over the target — a reader (or a concurrent writer,
    e.g. two SessionStart hooks racing on mcp-connections.json) always
    sees either the old complete content or the new complete content,
    never a partially-written file. ``os.replace`` is atomic on the same
    filesystem on both POSIX and Windows. source: review round 2 finding
    (pipeline_discovery.py's config write was a plain, non-atomic
    ``p.write_text``).
    
````

### ensure_dir, original line 59

````text
Ensure a directory exists, creating it recursively if needed.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
